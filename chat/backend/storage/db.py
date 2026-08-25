"""SQLModel database engine and session management.

Single SQLite file with WAL mode for concurrent reads.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

from sqlmodel import Session, SQLModel, create_engine, text

from backend.storage.models import *  # noqa: F401,F403 — register tables
from backend.utils.log import get_logger

logger = get_logger()

_engine = None
_current_db_path: str | None = None


def init_db(db_path: str) -> None:
    """Create the SQLite file (parents too), enable WAL, and run create_all.

    Idempotent. Safe to call on every startup.
    """
    global _engine, _current_db_path

    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.touch(exist_ok=True)

    url = f"sqlite:///{p.as_posix()}"
    _engine = create_engine(
        url,
        echo=False,
        connect_args={"check_same_thread": False},
    )

    # Enable WAL — readers don't block writers.
    with _engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.execute(text("PRAGMA foreign_keys=ON"))
        conn.commit()

    SQLModel.metadata.create_all(_engine)
    _current_db_path = str(p)
    logger.info("Database initialised at {}", p)


def get_engine():
    """Return the active engine. Raises if init_db() hasn't run yet."""
    if _engine is None:
        raise RuntimeError("DB not initialised — call init_db() first")
    return _engine


def get_session() -> Iterator[Session]:
    """FastAPI dependency: yields a Session, closes it on exit."""
    if _engine is None:
        raise RuntimeError("DB not initialised — call init_db() first")
    with Session(_engine) as session:
        yield session


def db_path() -> str:
    return _current_db_path or ""