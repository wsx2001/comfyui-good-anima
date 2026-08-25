"""danbooru-tags CLI wrapper.

Invokes ``bin/danbooru-tags.exe`` from the configured skills_root to
validate hard-anchor tags (character / copyright / artist).

Step 3 scope: batch validation of hard_tags before prompt assembly.
Failures return a per-tag breakdown so the LLM can retry with corrected
tags (fed back via the tool-result channel).
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Optional

from backend.config.loader import get_config
from backend.utils.log import get_logger

logger = get_logger()

# In-process cache: tag query → validated result. Tags are immutable data;
# cache for the process lifetime. Bounded to keep memory sane.
_CACHE: dict[str, dict] = {}
_CACHE_MAX = 2048


def _exe_path() -> Optional[Path]:
    root = get_config().comfyui.skills_root
    if not root:
        return None
    exe = Path(root) / "danbooru-tags" / "bin" / "danbooru-tags.exe"
    return exe if exe.exists() else None


async def validate_hard_tags(
    candidates: list[str],
    group: str = "general",
) -> dict:
    """Validate a batch of candidate tags against the local Anima index.

    Returns::

        {
          "confirmed": ["kanade tachibana", ...],
          "unknown":   ["not-a-real-tag", ...],
          "error":     null | "reason string"
        }

    Never raises — CLI absence / crashes are reported via ``error`` so the
    caller can decide whether to proceed without validation.
    """
    exe = _exe_path()
    if not exe:
        return {
            "confirmed": [],
            "unknown": candidates,
            "error": f"danbooru-tags.exe 未找到（skills_root 未配置或 bin 缺失）",
        }

    # Dedupe + consult cache first.
    uniq = list(dict.fromkeys(c.strip().lower() for c in candidates if c.strip()))
    results: dict[str, dict] = {}
    todo: list[str] = []
    for t in uniq:
        hit = _CACHE.get(f"{group}:{t}")
        if hit is not None:
            results[t] = hit["hit"]
        else:
            todo.append(t)

    if todo:
        try:
            started = time.time()
            proc = await asyncio.create_subprocess_exec(
                str(exe),
                "--batch-file",
                "-",
                "--group",
                group,
                "--json",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            payload = "\n".join(todo).encode("utf-8")
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(payload), timeout=30
            )
            if proc.returncode != 0:
                err = stderr.decode("utf-8", errors="replace")[:200]
                logger.warning("danbooru-tags exit {}: {}", proc.returncode, err)
                return {
                    "confirmed": [t for t, r in results.items() if r.get("valid")],
                    "unknown": [t for t in todo],
                    "error": f"CLI 退出码 {proc.returncode}: {err}",
                }

            parsed = json.loads(stdout.decode("utf-8"))
            elapsed = int((time.time() - started) * 1000)
            logger.info(
                "danbooru batch: {} queries in {}ms", len(todo), elapsed
            )

            # Expected shape: {"queries": [{query, valid/confirmed, matches...}]}
            # Be tolerant of minor shape differences; treat entries with a
            # truthy `valid` or non-empty `exact` as confirmed.
            for q in parsed.get("queries", []):
                tag = str(q.get("query") or "").strip().lower()
                valid = bool(q.get("valid")) or bool(q.get("exact")) or bool(q.get("confirmed"))
                entry = {"tag": tag, "valid": valid}
                results[tag] = entry
                key = f"{group}:{tag}"
                if len(_CACHE) < _CACHE_MAX:
                    _CACHE[key] = {"hit": entry}

        except asyncio.TimeoutError:
            return {
                "confirmed": [t for t, r in results.items() if r.get("valid")],
                "unknown": todo,
                "error": "danbooru-tags CLI 超时（30s）",
            }
        except json.JSONDecodeError as exc:
            return {
                "confirmed": [],
                "unknown": todo,
                "error": f"CLI 输出解析失败：{exc}",
            }
        except FileNotFoundError:
            return {
                "confirmed": [],
                "unknown": todo,
                "error": f"danbooru-tags.exe 不存在：{exe}",
            }

    confirmed = sorted({t for t, r in results.items() if r.get("valid")})
    unknown = sorted({t for t, r in results.items() if not r.get("valid")})
    return {"confirmed": confirmed, "unknown": unknown, "error": None}