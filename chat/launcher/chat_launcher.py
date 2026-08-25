"""Backend side of the ComfyUI launcher.

Registers two HTTP routes on ComfyUI's PromptServer:

  POST /good_anima_chat/launch  — probe whether the chat server is up.
                                  Returns ``{"ok": bool, "url": str}``.
  GET  /good_anima_chat/url     — return the configured chat URL.

The frontend button calls /launch first; if it returns ok=true, it pops
``/good_anima_chat/url`` in a new tab.

The chat URL is configurable via the ``GOOD_ANIMA_CHAT_URL`` env var.
Default is ``http://127.0.0.1:8787/`` matching the backend's default.

Tested with ComfyUI 0.3.x (``server.PromptServer.instance`` API).
"""
from __future__ import annotations

import os

from aiohttp import web

try:
    # ComfyUI 0.3+
    from server import PromptServer
except ImportError:  # pragma: no cover — older ComfyUI
    PromptServer = None

CHAT_URL = os.environ.get("GOOD_ANIMA_CHAT_URL", "http://127.0.0.1:8787/").rstrip("/") + "/"


async def _launch_handler(request: web.Request) -> web.Response:
    """Probe the chat backend's /api/health. Never raises — returns ok=False on error."""
    import httpx

    try:
        r = httpx.get(f"{CHAT_URL}api/health", timeout=2.0)
        ok = r.status_code == 200
    except Exception:
        ok = False
    return web.json_response({"ok": ok, "url": CHAT_URL})


async def _url_handler(request: web.Request) -> web.Response:
    return web.json_response({"url": CHAT_URL})


def _register_routes() -> None:
    """Idempotently attach our routes to the running PromptServer.

    ComfyUI's PromptServer.routes is a Router; adding the same path twice
    would warn, so we guard with a try/except in practice. We use
    ``router.add_post`` which raises if the resource already exists.
    """
    if PromptServer is None or not hasattr(PromptServer, "instance"):
        # ComfyUI not available (e.g. running this file standalone) — no-op.
        return
    routes = PromptServer.instance.routes
    try:
        routes.post("/good_anima_chat/launch")(_launch_handler)
    except Exception:
        pass  # already registered
    try:
        routes.get("/good_anima_chat/url")(_url_handler)
    except Exception:
        pass


_register_routes()


# No workflow nodes — this is purely a UI launcher.
NODE_CLASS_MAPPINGS: dict = {}

# Tells ComfyUI to mount this directory as a static asset root,
# and to look for *.js files to load as front-end extensions.
WEB_DIRECTORY = "./web"