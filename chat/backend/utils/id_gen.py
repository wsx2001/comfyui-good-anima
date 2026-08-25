"""Compact, sortable, URL-safe unique IDs.

We use ULID (Crockford base-32, 26 chars) over UUIDv4 because:
  - Lexicographically sortable by time → natural conversation/message ordering
  - Shorter and more readable in URLs, logs, DB rows
  - No extra dependency required for this simplified form

Format: ``01HXY...Z`` — first 10 chars are time, last 16 are random.
"""
from __future__ import annotations

import os
import time

# Crockford's base-32 alphabet (excludes I, L, O, U to avoid confusion).
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode_time(ms: int) -> str:
    """Encode a 48-bit millisecond timestamp into 10 base-32 chars."""
    out = []
    for _ in range(10):
        out.append(_ALPHABET[ms & 0x1F])
        ms >>= 5
    return "".join(reversed(out))


def _encode_random() -> str:
    """16 base-32 chars from os.urandom(80 bits) — collision-resistant for our scale."""
    rand_bytes = os.urandom(10)
    val = int.from_bytes(rand_bytes, "big")
    out = []
    for _ in range(16):
        out.append(_ALPHABET[val & 0x1F])
        val >>= 5
    return "".join(reversed(out))


def new_id() -> str:
    """Generate a fresh ULID.

    Returns a 26-char string, e.g. ``01JB3X7Y8Z9R4T2G5K6NQFVWA3``.
    """
    ms = int(time.time() * 1000)
    return _encode_time(ms) + _encode_random()