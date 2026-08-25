"""Load and persist application settings.

Resolution order (highest priority first):
  1. Environment variables prefixed with ``COMFYUI_CHAT_``
  2. ``backend/runtime/config.json`` (created with defaults on first run)

API key handling:
  - ``COMFYUI_CHAT_LLM_API_KEY`` always wins over the JSON file
  - When written back to JSON, the key is masked (``sk-***1234``)
    so a casual file read doesn't leak secrets. The real key is held
    in-memory and re-merged on every read.
"""
from __future__ import annotations

import copy
import json
import os
from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError

from backend.config.schema import Settings
from backend.utils.log import get_logger

logger = get_logger()

_RUNTIME_DIR = Path(__file__).resolve().parent.parent / "runtime"
_CONFIG_FILE = _RUNTIME_DIR / "config.json"
_SECRET_FILE = _RUNTIME_DIR / ".secrets.json"  # holds api_key unmasked
_MASK = "***"


def _mask_key(key: str) -> str:
    """Mask an API key for safe JSON persistence: ``sk-abc...xyz`` → ``sk-***xyz``."""
    if not key:
        return ""
    if len(key) <= 8:
        return _MASK
    return f"{key[:3]}{_MASK}{key[-4:]}"


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Invalid JSON at {}; ignoring", path)
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _apply_env_overrides(data: dict) -> dict:
    """Overlay ``COMFYUI_CHAT_*`` env vars onto the dict.

    Mapping (env → JSON path):
      COMFYUI_CHAT_PORT              → server.port
      COMFYUI_CHAT_LLM_API_KEY       → llm.api_key
      COMFYUI_CHAT_LLM_BASE_URL      → llm.base_url
      COMFYUI_CHAT_LLM_MODEL         → llm.model
      COMFYUI_CHAT_LLM_TEMPERATURE   → llm.temperature
      COMFYUI_CHAT_LLM_MAX_TOKENS    → llm.max_tokens
      COMFYUI_CHAT_LLM_REASONING     → llm.reasoning_effort
      COMFYUI_CHAT_LLM_CONTEXT       → llm.context_window
      COMFYUI_CHAT_SKILLS_ROOT       → comfyui.skills_root
    """
    out = copy.deepcopy(data)

    def set_nested(path: str, value):
        keys = path.split(".")
        d = out
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = value

    env_map = {
        "COMFYUI_CHAT_PORT": ("server.port", int),
        "COMFYUI_CHAT_LLM_API_KEY": ("llm.api_key", str),
        "COMFYUI_CHAT_LLM_BASE_URL": ("llm.base_url", str),
        "COMFYUI_CHAT_LLM_MODEL": ("llm.model", str),
        "COMFYUI_CHAT_LLM_TEMPERATURE": ("llm.temperature", float),
        "COMFYUI_CHAT_LLM_MAX_TOKENS": ("llm.max_tokens", int),
        "COMFYUI_CHAT_LLM_REASONING": ("llm.reasoning_effort", str),
        "COMFYUI_CHAT_LLM_CONTEXT": ("llm.context_window", int),
        "COMFYUI_CHAT_SKILLS_ROOT": ("comfyui.skills_root", str),
    }
    for env_name, (json_path, caster) in env_map.items():
        raw = os.environ.get(env_name)
        if raw is None or raw == "":
            continue
        try:
            set_nested(json_path, caster(raw))
        except (ValueError, TypeError) as exc:
            logger.warning("Bad env {}={!r}: {}", env_name, raw, exc)

    return out


def load_config() -> Settings:
    """Build a ``Settings`` from disk + env, creating defaults on first run."""
    _RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    on_disk = _read_json(_CONFIG_FILE)
    secrets = _read_json(_SECRET_FILE)  # small file, holds real api_key

    # Real key from .secrets.json always overrides disk (where it's masked).
    real_key = (secrets.get("llm") or {}).get("api_key") or ""
    if real_key:
        on_disk.setdefault("llm", {})["api_key"] = real_key

    merged = _apply_env_overrides(on_disk)
    try:
        return Settings(**merged)
    except ValidationError as exc:
        logger.error("Settings validation failed: {}; using defaults", exc)
        return Settings()


def save_config(settings: Settings) -> None:
    """Persist settings. The API key is masked in config.json and kept plain in .secrets.json."""
    _RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    dumped = settings.model_dump()
    real_key = dumped.get("llm", {}).get("api_key", "")
    masked = copy.deepcopy(dumped)
    masked.setdefault("llm", {})["api_key"] = _mask_key(real_key)

    _write_json(_CONFIG_FILE, masked)

    # Keep .secrets.json in sync so subsequent loads re-resolve the key.
    secrets = {"llm": {"api_key": real_key}} if real_key else {"llm": {"api_key": ""}}
    _write_json(_SECRET_FILE, secrets)

    # Invalidate the cache so the next get_config() re-reads.
    get_config.cache_clear()


@lru_cache(maxsize=1)
def get_config() -> Settings:
    """Cached settings accessor used by all modules."""
    return load_config()


def reset_config_cache() -> None:
    """Force re-read of the config file (used after PUT /api/settings)."""
    get_config.cache_clear()