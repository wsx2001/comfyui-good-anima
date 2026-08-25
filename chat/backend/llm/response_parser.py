"""Parse OpenAI-compatible streaming responses into our internal events.

We accept both the standard ``delta.content`` / ``delta.tool_calls`` shape
and DeepSeek-R1's extra ``delta.reasoning_content`` field.

Output event types (matches the SSE event names from TECH §5.2):

  - ("reasoning", text)
  - ("content", text)
  - ("tool_call", {index, id, name, arguments_delta})
  - ("finish", finish_reason)
  - ("error", message)
"""
from __future__ import annotations

import json
from typing import AsyncIterator, Iterator

# Event type constants (string-based to keep SSE-friendly)
EVT_REASONING = "reasoning"
EVT_CONTENT = "content"
EVT_TOOL_CALL = "tool_call"
EVT_FINISH = "finish"
EVT_ERROR = "error"


def _coerce_str(value) -> str:
    """Provider may return content as None, str, or list-of-parts. Normalise to str."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        # OpenAI structured outputs: list of {"type":"text","text":"..."} etc.
        return "".join(p.get("text", "") for p in value if isinstance(p, dict))
    return str(value)


class ToolCallAccumulator:
    """Buffer for streaming tool_call deltas — they arrive piece by piece.

    The first chunk for a given index has id/name; subsequent chunks have
    only ``arguments`` deltas. We accumulate both per index.
    """

    def __init__(self) -> None:
        self._calls: dict[int, dict] = {}

    def feed(self, delta_calls: list[dict]) -> list[tuple[int, str, str, str]]:
        """Apply a delta's tool_calls. Return list of (index, id, name, args_so_far)
        for any call whose state changed since the last chunk.
        """
        changed: list[tuple[int, str, str, str]] = []
        if not delta_calls:
            return changed
        for d in delta_calls:
            idx = d.get("index")
            if idx is None:
                continue
            cur = self._calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
            # `id` and `name` arrive only on the first chunk for that index.
            if d.get("id") is not None:
                cur["id"] = (cur["id"] or "") + d["id"]
            func = d.get("function") or {}
            if func.get("name"):
                cur["name"] = func["name"]
            if "arguments" in func and func["arguments"] is not None:
                cur["arguments"] += func["arguments"]
            changed.append((idx, cur["id"], cur["name"], cur["arguments"]))
        return changed

    def finalise(self) -> list[dict]:
        """Return one complete tool_call dict per index, ready for the DB / chat_service."""
        return [
            {
                "index": idx,
                "id": c["id"],
                "type": "function",
                "function": {"name": c["name"], "arguments": c["arguments"]},
            }
            for idx, c in sorted(self._calls.items())
        ]


def parse_stream(chunks: Iterator[dict]) -> Iterator[tuple[str, object]]:
    """Parse a synchronous stream of OpenAI completion chunks.

    Use ``parse_async_stream`` for the async variant.
    """
    tools = ToolCallAccumulator()
    for chunk in chunks:
        evt = _chunk_to_event(chunk, tools)
        if evt is not None:
            yield evt


async def parse_async_stream(chunks: AsyncIterator[dict]) -> AsyncIterator[tuple[str, object]]:
    """Parse an async stream of OpenAI completion chunks."""
    tools = ToolCallAccumulator()
    async for chunk in chunks:
        evt = _chunk_to_event(chunk, tools)
        if evt is not None:
            yield evt


def _chunk_to_event(chunk: dict, tools: ToolCallAccumulator):
    """Convert one chunk into an event or None (skip)."""
    try:
        choices = chunk.get("choices") or []
    except AttributeError:
        return (EVT_ERROR, "invalid chunk shape (no choices)")

    if not choices:
        return None

    delta = choices[0].get("delta") or {}

    # Reasoning (DeepSeek-R1 / o1 extended thinking).
    # Provider may name this field `reasoning_content` or `reasoning`.
    reasoning_text = delta.get("reasoning_content") or delta.get("reasoning")
    if reasoning_text:
        return (EVT_REASONING, _coerce_str(reasoning_text))

    # Content
    content_text = _coerce_str(delta.get("content"))
    if content_text:
        return (EVT_CONTENT, content_text)

    # Tool calls — accumulate and emit on every change.
    tool_calls_delta = delta.get("tool_calls")
    if tool_calls_delta:
        changed = tools.feed(tool_calls_delta)
        if changed:
            # Emit the last one (others are subsets of the accumulator state).
            idx, _id, name, args = changed[-1]
            return (
                EVT_TOOL_CALL,
                {"index": idx, "id": _id, "name": name, "arguments_delta": args},
            )
        return None

    # Finish reason (last chunk usually)
    finish = choices[0].get("finish_reason")
    if finish:
        return (EVT_FINISH, {"reason": finish, "tool_calls": tools.finalise()})

    return None


# ---------------------------------------------------------------------------
# SSE event serialisation
# ---------------------------------------------------------------------------


def sse_format(event: str, data: object) -> str:
    """Format one SSE message per the spec: ``event: <name>\\ndata: <json>\\n\\n``."""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"