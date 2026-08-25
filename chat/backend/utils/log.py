"""Centralised loguru configuration.

Import as ``from backend.utils.log import logger`` — the same logger is
shared across modules.
"""
from __future__ import annotations

import sys

from loguru import logger as _logger

# Default sink: stderr, colored, with timestamp + level + module.
_logger.remove()
_logger.add(
    sys.stderr,
    level="INFO",
    format=(
        "<green>{time:HH:mm:ss.SSS}</green> "
        "| <level>{level: <8}</level> "
        "| <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> "
        "- <level>{message}</level>"
    ),
    enqueue=False,
)


def get_logger():
    """Return the configured loguru logger."""
    return _logger