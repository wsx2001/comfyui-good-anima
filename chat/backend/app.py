"""FastAPI app factory and lifespan.

Run via ``python -m backend`` (see ``backend.__main__``).
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend import __version__
from backend.api import conversations, health, images, jobs, messages, queues, settings
from backend.config.loader import get_config
from backend.storage.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB on startup; re-attach pollers for jobs left running."""
    cfg = get_config()
    init_db(cfg.storage.db_path)
    from backend.services import job_queue, job_service

    job_service.recover_running_jobs()
    # M1: queues do NOT auto-resume — mark orphans failed so the UI is honest.
    job_queue.recover_stale_queues()
    yield


def create_app() -> FastAPI:
    """Build and return the FastAPI application.

    Routers are mounted under ``/api``. Static SPA assets (if built) are
    served from the same origin so the user just visits ``/``.
    """
    app = FastAPI(
        title="ComfyUI Good Anima Chat",
        version=__version__,
        lifespan=lifespan,
    )
    app.include_router(health.router, prefix="/api")
    app.include_router(settings.router, prefix="/api")
    app.include_router(conversations.router, prefix="/api")
    app.include_router(messages.router, prefix="/api")
    app.include_router(jobs.router, prefix="/api")
    app.include_router(images.router, prefix="/api")
    app.include_router(queues.router, prefix="/api")

    # Serve the built SPA from the same origin (production mode).
    # In dev, the user runs `npm run dev` and Vite proxies /api to us.
    dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if dist.exists() and dist.is_dir():
        index_html = dist / "index.html"

        # Real static assets (JS / CSS / images) come from /assets/*
        app.mount(
            "/assets",
            StaticFiles(directory=str(dist / "assets")),
            name="assets",
        )

        # SPA fallback: any non-/api GET that doesn't match a real file
        # returns index.html so vue-router can take over.
        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            # Don't shadow /api/* — those should 404 normally.
            if full_path.startswith("api/"):
                from fastapi import HTTPException

                raise HTTPException(status_code=404, detail="Not Found")
            return FileResponse(str(index_html))

    return app