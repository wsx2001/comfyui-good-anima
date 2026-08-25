"""OpenAI-compatible LLM client (sync + streaming).

``client.test_llm`` (Step 1) — ping the model with a tiny request.
``client.stream_chat`` (Step 2) — async generator over OpenAI stream chunks.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import AsyncIterator

import httpx
from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    OpenAI,
)

from backend.config.loader import get_config
from backend.utils.log import get_logger

logger = get_logger()


# ---------------------------------------------------------------------------
# Sync helpers (test_llm + probe_comfyui unchanged from M0)
# ---------------------------------------------------------------------------


def test_llm(base_url: str, api_key: str, model: str, timeout: int = 10) -> dict:
    """Send a minimal chat completion request and return success/failure."""
    started = time.time()
    if not api_key:
        return {"ok": False, "error_code": "no_api_key", "error_message": "API key 未填写"}
    if not base_url:
        return {"ok": False, "error_code": "no_base_url", "error_message": "Base URL 未填写"}
    if not model:
        return {"ok": False, "error_code": "no_model", "error_message": "Model 未填写"}

    try:
        client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=10,
        )
        return {
            "ok": True,
            "model": resp.model,
            "latency_ms": int((time.time() - started) * 1000),
        }
    except APITimeoutError:
        return {"ok": False, "error_code": "timeout", "error_message": "LLM API 超时"}
    except APIStatusError as exc:
        return {
            "ok": False,
            "error_code": str(exc.status_code),
            "error_message": (exc.message or str(exc))[:200],
        }
    except APIConnectionError as exc:
        return {"ok": False, "error_code": "connection", "error_message": str(exc)[:200]}
    except APIError as exc:
        return {"ok": False, "error_code": "api_error", "error_message": str(exc)[:200]}
    except Exception as exc:  # pragma: no cover — defensive
        logger.exception("Unexpected LLM test error")
        return {"ok": False, "error_code": "unknown", "error_message": str(exc)[:200]}


def probe_comfyui(config_json_path: str, timeout: int = 3) -> bool:
    """Read the v2mini config.json and GET ComfyUI's /system_stats."""
    if not config_json_path:
        return False
    p = Path(config_json_path)
    if not p.exists():
        return False
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
        servers = cfg.get("servers") or []
        if not servers:
            return False
        url = (servers[0].get("url") or "").rstrip("/")
        if not url:
            return False
        r = httpx.get(f"{url}/system_stats", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Streaming chat (Step 2)
# ---------------------------------------------------------------------------


def _build_request_params(
    *,
    model: str,
    messages: list[dict],
    tools: list[dict] | None,
    temperature: float,
    max_tokens: int,
    reasoning_effort: str,
) -> dict:
    """Compose the request kwargs for ``chat.completions.create``.

    Notes:
      - ``reasoning_effort`` is a non-standard field. Some providers ignore
        it silently; we don't try to validate upstream.
      - ``tools`` is forwarded as-is so the OpenAI SDK serialises them
        in the function-calling shape providers expect.
    """
    params: dict = {
        "model": model,
        "messages": messages,
        "stream": True,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        params["tools"] = tools
        # ``tool_choice`` defaults to "auto" — LLM decides when to call.

    # ``reasoning_effort`` isn't in the OpenAI SDK's typed ChatCompletion
    # schema (it's a Responses-API-only field). We use ``extra_body`` to
    # pass it through unmodified for providers that recognise it
    # (DeepSeek, Anthropic-via-proxy, etc.). Providers that ignore unknown
    # body fields will silently drop it.
    extra: dict = {}
    if reasoning_effort and reasoning_effort != "off":
        extra["reasoning_effort"] = reasoning_effort
    if extra:
        params["extra_body"] = extra
    return params


async def stream_chat(
    messages: list[dict],
    tools: list[dict] | None = None,
) -> AsyncIterator[dict]:
    """Async-generate OpenAI streaming completion chunks.

    Yields raw chunk dicts exactly as the SDK delivers them. The caller
    is responsible for parsing (``llm.response_parser``).
    """
    cfg = get_config()
    client = AsyncOpenAI(
        base_url=cfg.llm.base_url,
        api_key=cfg.llm.api_key or "no-key",
        timeout=httpx.Timeout(60.0, connect=10.0),
    )
    params = _build_request_params(
        model=cfg.llm.model,
        messages=messages,
        tools=tools,
        temperature=cfg.llm.temperature,
        max_tokens=cfg.llm.max_tokens,
        reasoning_effort=cfg.llm.reasoning_effort,
    )
    logger.info(
        "stream_chat → model={} base={} messages={} tools={} reasoning={}",
        cfg.llm.model,
        cfg.llm.base_url,
        len(messages),
        len(tools or []),
        cfg.llm.reasoning_effort,
    )
    try:
        stream = await client.chat.completions.create(**params)
        async for chunk in stream:
            # Each chunk is a pydantic model; serialise to dict for our parser.
            yield chunk.model_dump() if hasattr(chunk, "model_dump") else dict(chunk)
    except APITimeoutError:
        raise RuntimeError("LLM API 超时")
    except APIStatusError as exc:
        raise RuntimeError(f"LLM API {exc.status_code}: {(exc.message or str(exc))[:200]}")
    except APIConnectionError as exc:
        raise RuntimeError(f"LLM API 连接失败：{str(exc)[:200]}")
    except APIError as exc:
        raise RuntimeError(f"LLM API 错误：{str(exc)[:200]}")