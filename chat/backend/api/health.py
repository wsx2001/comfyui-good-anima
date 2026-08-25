"""Health probe for /api/health.

Returns a snapshot of the dependencies the backend needs to function:
  - DB is reachable
  - ComfyUI HTTP server is reachable
  - LLM is configured (api_key present)

A failed dependency doesn't make ``status != "ok"`` — the backend can
still serve the Settings page even if ComfyUI is offline. We just report.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session, text

from backend import __version__
from backend.config.loader import get_config
from backend.llm.client import probe_comfyui
from backend.storage.db import get_session

router = APIRouter()


@router.get("/health")
def health(session: Session = Depends(get_session)) -> dict:
    """Liveness + dependency probe."""
    cfg = get_config()

    # DB ping
    try:
        db_ok = session.exec(text("SELECT 1")).first() is not None
    except Exception:
        db_ok = False

    comfyui_ok = probe_comfyui(cfg.comfyui.config_json) if cfg.comfyui.config_json else False
    llm_ok = bool(cfg.llm.api_key)

    return {
        "status": "ok" if db_ok else "degraded",
        "db_ok": db_ok,
        "comfyui_reachable": comfyui_ok,
        "llm_configured": llm_ok,
        "version": __version__,
    }