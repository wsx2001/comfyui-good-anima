"""Args validation for the v2mini flat-args protocol.

The LLM produces args inside ``submit_image_gen`` tool calls; this module
is the second gate (after the JSON-schema tool definition) before anything
reaches ComfyUI.

Missing/invalid fields produce a Chinese-language error listing exactly
what to fix — that string is fed back to the LLM as the tool result so it
can retry with corrected args.
"""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field, ValidationError

# filename_prefix: keep it filesystem-safe (v2mini writes files with it).
_PREFIX_RE = re.compile(r"^[\w\-]+$")


class V2MiniArgs(BaseModel):
    """Flat args object accepted by ``run_workflow_args.js``."""

    prompt_11: str = Field(min_length=1, description="正向 prompt")
    prompt_12: str = Field(min_length=1, description="负向 prompt")
    width: int = Field(ge=64, le=4096)
    height: int = Field(ge=64, le=4096)
    batch_size: int = Field(default=1, ge=1, le=8)
    steps: int = Field(ge=1, le=100)
    cfg: float = Field(default=4.5, ge=0.0, le=30.0)
    seed: Optional[int] = None
    filename_prefix: str = Field(min_length=1, max_length=64)
    rtx_vsr_quality: str = Field(default="ULTRA")

    def model_post_init(self, __context) -> None:
        if not _PREFIX_RE.match(self.filename_prefix):
            raise ValueError(
                f"filename_prefix 只能含字母数字下划线连字符，得到 {self.filename_prefix!r}"
            )


def validate_args(raw: dict) -> tuple[Optional[V2MiniArgs], Optional[str]]:
    """Validate raw tool-call args.

    Returns ``(args, None)`` on success or ``(None, error_message)`` where
    error_message is a Chinese description suitable for feeding back to the LLM.
    """
    if not isinstance(raw, dict):
        return None, f"args 必须是对象，得到 {type(raw).__name__}"

    # Fill defaults from conversation-level settings is caller's job; here
    # we only enforce required keys exist at all so error messages are precise.
    missing = [
        k
        for k in ("prompt_11", "prompt_12", "width", "height", "steps", "filename_prefix")
        if k not in raw
    ]
    if missing:
        return None, f"args 缺少必需字段：{', '.join(missing)}"

    try:
        return V2MiniArgs(**raw), None
    except ValidationError as exc:
        problems = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"]) or "(root)"
            problems.append(f"{loc}: {err['msg']}")
        return None, "args 校验失败：" + "；".join(problems[:5])
