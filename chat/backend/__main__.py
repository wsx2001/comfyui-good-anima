"""Entry point: ``python -m backend`` starts the FastAPI server on 127.0.0.1:8787."""

import uvicorn

from backend.app import create_app
from backend.config.loader import get_config


def main() -> None:
    """Boot uvicorn with the configured host/port and the app factory's output."""
    cfg = get_config()
    app = create_app()
    uvicorn.run(
        app,
        host=cfg.server.host,
        port=cfg.server.port,
        log_level="info",
        # Don't reload — we're a desktop tool, not a dev server.
        reload=False,
    )


if __name__ == "__main__":
    main()