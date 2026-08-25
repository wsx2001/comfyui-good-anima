"""Settings endpoints.

GET  /api/settings          — current config (api_key masked)
PUT  /api/settings          — replace the config
POST /api/settings/test_llm — try the configured (or supplied) LLM
POST /api/settings/reset    — restore defaults

The api_key returned by GET is masked for safety. The real key lives in
``runtime/.secrets.json`` (mode 600 on Unix, plain on Windows) and is
re-merged on every read by the loader.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from backend.config.loader import (
    _mask_key,
    get_config,
    reset_config_cache,
    save_config,
)
from backend.config.schema import Settings
from backend.llm.client import test_llm
from backend.utils.log import get_logger

logger = get_logger()

router = APIRouter()


def _masked_view(settings: Settings) -> dict:
    """Return settings dict with the api_key masked."""
    dumped = settings.model_dump()
    api_key = dumped.get("llm", {}).get("api_key", "")
    if api_key:
        dumped["llm"]["api_key"] = _mask_key(api_key)
    return dumped


@router.get("/settings")
def get_settings() -> dict:
    return _masked_view(get_config())


@router.put("/settings")
def update_settings(payload: Settings) -> dict:
    save_config(payload)
    return {"ok": True}


@router.post("/settings/reload")
def reload_settings() -> dict:
    """Force re-read from disk (no state change)."""
    reset_config_cache()
    return {"ok": True}


class TestLLMReq(BaseModel):
    """Override values for the test call. Empty fields fall back to current config."""

    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    timeout: int | None = None


@router.post("/settings/test_llm")
def test_llm_endpoint(req: TestLLMReq) -> dict:
    cfg = get_config()
    base_url = req.base_url or cfg.llm.base_url
    api_key = req.api_key or cfg.llm.api_key
    model = req.model or cfg.llm.model
    timeout = req.timeout or 10
    result = test_llm(base_url, api_key, model, timeout=timeout)
    logger.info("test_llm: {}", result)
    return result