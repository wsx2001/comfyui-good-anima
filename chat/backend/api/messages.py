"""Messages endpoint — Step 2 streaming LLM integration.

POST /api/conversations/{id}/messages returns a text/event-stream
(SSE) response. Events emitted:

  event: message.start   data: {"user_message_id": "...", "assistant_message_id": "..."}
  event: reasoning.delta data: {"delta": "..."}
  event: content.delta   data: {"delta": "..."}
  event: tool.call       data: {"index": 0, "name": "...", "arguments": {...}}
  event: message.end     data: {"finish_reason": "stop", "content": "...", "reasoning": "..."}
  event: error           data: {"message": "...", "code": "..."}

Step 2 notes:
  - User message is persisted before streaming starts.
  - Assistant message is persisted at message.end with the full content.
  - Tool calls are NOT executed yet — Step 3 will run them.
  - The final assistant message always gets a DB row even if the LLM
    produced only tool calls (content falls back to a placeholder).
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from backend.config.loader import get_config
from backend.llm.client import stream_chat
from backend.llm.prompt_builder import get_cached_system_prompt
from backend.llm.response_parser import (
    EVT_CONTENT,
    EVT_FINISH,
    EVT_REASONING,
    EVT_TOOL_CALL,
    parse_async_stream,
    sse_format,
)
from backend.llm.tool_definitions import ALL_TOOLS
from backend.services.chat_service import MAX_TOOL_ROUNDS, execute_tool
from backend.storage.db import get_engine, get_session
from backend.storage.models import Conversation, Message
from backend.utils.id_gen import new_id
from backend.utils.log import get_logger

router = APIRouter()
logger = get_logger()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class MessageCreate(BaseModel):
    content: str
    workflow_id: Optional[str] = None
    client_msg_id: Optional[str] = None


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    reasoning: Optional[str] = None
    job_id: Optional[str] = None
    created_at: str


# ---------------------------------------------------------------------------
# List endpoint (unchanged from Step 1)
# ---------------------------------------------------------------------------


@router.get("/conversations/{conv_id}/messages")
def list_messages(
    conv_id: str,
    session: Session = Depends(get_session),
) -> list[dict]:
    conv = session.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    msgs = session.exec(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.asc())
    ).all()
    return [
        MessageOut(
            id=m.id,
            role=m.role,
            content=m.content,
            reasoning=m.reasoning,
            job_id=m.job_id,
            created_at=m.created_at.isoformat(),
        ).model_dump()
        for m in msgs
    ]


# ---------------------------------------------------------------------------
# Send + stream (Step 2)
# ---------------------------------------------------------------------------


def _sse(event: str, data: dict) -> bytes:
    """Format one SSE message and encode to bytes."""
    return sse_format(event, data).encode("utf-8")


def _load_history(conversation_id: str, limit: int) -> list[Message]:
    """Load the last ``limit`` messages for a conversation, ordered ASC."""
    with Session(get_engine()) as session:
        msgs = session.exec(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        ).all()
        msgs.reverse()
        return msgs


def _persist_user_message(conversation_id: str, content: str) -> Message:
    """Insert the user message and return it."""
    with Session(get_engine()) as session:
        msg = Message(
            id=new_id(),
            conversation_id=conversation_id,
            role="user",
            content=content,
            reasoning=None,
            job_id=None,
            created_at=datetime.utcnow(),
        )
        session.add(msg)
        session.commit()
        session.refresh(msg)
        return msg


def _persist_assistant_message(
    conversation_id: str,
    content: str,
    reasoning: Optional[str],
) -> Message:
    """Insert the assistant message at end-of-stream."""
    placeholder = "(empty)" if not content.strip() else content
    with Session(get_engine()) as session:
        msg = Message(
            id=new_id(),
            conversation_id=conversation_id,
            role="assistant",
            content=placeholder,
            reasoning=reasoning,
            job_id=None,
            created_at=datetime.utcnow(),
        )
        session.add(msg)
        # Bump conversation timestamp + auto-title.
        conv = session.get(Conversation, conversation_id)
        if conv:
            conv.updated_at = datetime.utcnow()
            if not conv.title or conv.title == "新会话":
                first_user = session.exec(
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .where(Message.role == "user")
                    .order_by(Message.created_at.asc())
                ).first()
                if first_user:
                    txt = first_user.content
                    conv.title = (txt[:20] + "…") if len(txt) > 20 else txt
            session.add(conv)
        session.commit()
        session.refresh(msg)
        return msg


def _history_to_llm_messages(history: list[Message]) -> list[dict]:
    """Convert internal Message rows to the LLM's expected shape."""
    out: list[dict] = []
    for m in history:
        if m.role not in ("user", "assistant", "system"):
            continue
        msg: dict = {"role": m.role, "content": m.content}
        # OpenAI doesn't store reasoning as a separate turn; we collapse it
        # into a system note so the LLM can reference prior thinking.
        if m.reasoning and m.role == "assistant":
            msg["content"] = f"<!--prior reasoning:\n{m.reasoning}\n-->\n{m.content}"
        out.append(msg)
    return out


@router.post("/conversations/{conv_id}/messages")
async def create_message_stream(
    conv_id: str,
    body: MessageCreate,
) -> StreamingResponse:
    # ----- Pre-stream validation -----
    with Session(get_engine()) as session:
        conv = session.get(Conversation, conv_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="content is empty")

    cfg = get_config()
    if not cfg.llm.api_key:
        raise HTTPException(status_code=400, detail="LLM API key 未配置，请先在设置页填写")
    if not cfg.llm.model:
        raise HTTPException(status_code=400, detail="LLM model 未配置")

    # ----- Persist user message BEFORE streaming -----
    user_msg = _persist_user_message(conv_id, body.content)
    assistant_id = new_id()  # reserved — created on stream end

    async def event_generator() -> AsyncIterator[bytes]:
        # Emit message.start with both reserved IDs.
        yield _sse(
            "message.start",
            {
                "user_message_id": user_msg.id,
                "assistant_message_id": assistant_id,
            },
        )

        # Build the LLM call.
        try:
            history = _load_history(conversation_id=conv_id, limit=max(cfg.llm.context_window * 2, 6))
            llm_messages: list[dict] = [
                {"role": "system", "content": get_cached_system_prompt()}
            ]
            llm_messages.extend(_history_to_llm_messages(history))

            content_buf: list[str] = []
            reasoning_buf: list[str] = []
            executed_tools: list[dict] = []

            # Multi-turn tool-use loop (bounded): each round streams one LLM
            # completion; when it ends with tool calls we execute them, append
            # the results, and loop. Rounds without tool calls end the chat.
            for round_no in range(MAX_TOOL_ROUNDS):
                round_content: list[str] = []
                round_tool_calls: dict[int, dict] = {}
                finish_reason: str | None = None

                chunks = stream_chat(llm_messages, tools=ALL_TOOLS)

                async for evt_type, evt_data in parse_async_stream(chunks):
                    if evt_type == EVT_REASONING:
                        text = str(evt_data)
                        reasoning_buf.append(text)
                        yield _sse("reasoning.delta", {"delta": text})

                    elif evt_type == EVT_CONTENT:
                        text = str(evt_data)
                        content_buf.append(text)
                        round_content.append(text)
                        yield _sse("content.delta", {"delta": text})

                    elif evt_type == EVT_TOOL_CALL:
                        info = evt_data if isinstance(evt_data, dict) else {}
                        idx = info.get("index", 0)
                        cur = round_tool_calls.setdefault(
                            idx, {"id": "", "name": "", "arguments": ""}
                        )
                        if info.get("id"):
                            cur["id"] = info["id"]
                        if info.get("name"):
                            cur["name"] = info["name"]
                        if info.get("arguments_delta") is not None:
                            cur["arguments"] += info["arguments_delta"]
                        args_preview: object = cur["arguments"]
                        try:
                            args_preview = json.loads(cur["arguments"])
                        except Exception:
                            pass
                        yield _sse(
                            "tool.call",
                            {
                                "index": idx,
                                "id": cur["id"],
                                "name": cur["name"],
                                "arguments": args_preview,
                            },
                        )

                    elif evt_type == EVT_FINISH:
                        info = evt_data if isinstance(evt_data, dict) else {}
                        finish_reason = info.get("reason")
                        # Prefer complete snapshot from finish over deltas.
                        snap = info.get("tool_calls") or []
                        if snap:
                            round_tool_calls.clear()
                            for tc in snap:
                                round_tool_calls[tc["index"]] = {
                                    "id": tc["id"],
                                    "name": tc["function"]["name"],
                                    "arguments": tc["function"]["arguments"],
                                }
                        break

                # No tool calls this round → conversation turn is done.
                if not round_tool_calls:
                    break

                # Execute tools (Step 3: submit_image_gen / validate_tags).
                assistant_partial = "".join(round_content).strip()
                llm_messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_partial or None,
                        "tool_calls": [
                            {
                                "id": c["id"] or f"call_{idx}",
                                "type": "function",
                                "function": {
                                    "name": c["name"],
                                    "arguments": c["arguments"] or "{}",
                                },
                            }
                            for idx, c in sorted(round_tool_calls.items())
                        ],
                    }
                )

                for idx, call in sorted(round_tool_calls.items()):
                    name = call["name"]
                    try:
                        arguments = json.loads(call["arguments"]) if call["arguments"] else {}
                    except json.JSONDecodeError:
                        arguments = {}
                        result = {"ok": False, "error": f"工具参数不是合法 JSON"}
                    else:
                        result = await execute_tool(
                            name=name,
                            arguments=arguments,
                            conversation_id=conv_id,
                            assistant_message_id=None,
                        )
                    executed_tools.append({"name": name, "result": result})
                    yield _sse("tool.result", {"index": idx, "name": name, "result": result})
                    llm_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"] or f"call_{idx}",
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )

                logger.info(
                    "round {} executed {} tool call(s); looping LLM", round_no + 1,
                    len(round_tool_calls),
                )
            else:
                logger.warning("tool-round cap {} reached", MAX_TOOL_ROUNDS)

            yield _sse(
                "message.end",
                {"finish_reason": finish_reason or "stop", "tools_executed": len(executed_tools)},
            )

            # ----- Persist assistant message at end of stream -----
            full_content = "".join(content_buf).strip()
            full_reasoning = "".join(reasoning_buf).strip() or None
            if not full_content and executed_tools:
                tool_names = sorted({t["name"] for t in executed_tools})
                full_content = f"（已执行工具：{', '.join(tool_names)}）"
            persisted = _persist_assistant_message(
                conversation_id=conv_id,
                content=full_content,
                reasoning=full_reasoning,
            )
            logger.info(
                "Stream done: user={} assistant={} content={}ch reasoning={}ch tools={}",
                user_msg.id,
                persisted.id,
                len(full_content),
                len(full_reasoning or ""),
                len(executed_tools),
            )

        except Exception as exc:  # network / parse / etc.
            logger.exception("Stream failed")
            yield _sse("error", {"message": str(exc)[:200], "code": "stream_failed"})
            # Still persist whatever we have so the user sees a partial reply.
            full_content = "".join(content_buf).strip() or "(流式中断，未收到完整内容)"
            full_reasoning = "".join(reasoning_buf).strip() or None
            try:
                _persist_assistant_message(
                    conversation_id=conv_id,
                    content=full_content,
                    reasoning=full_reasoning,
                )
            except Exception:
                logger.exception("Failed to persist partial assistant message")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx-style buffering
        },
    )