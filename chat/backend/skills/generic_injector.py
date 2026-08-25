"""Placeholder for user-imported workflows (M2).

M1 rejects any non-v2mini workflow_id with a clear error so the LLM gets
actionable feedback instead of a silent failure.
"""
from __future__ import annotations

from pathlib import Path


class GenericInjector:
    mode = "generic"

    def __init__(self, workflow_id: str):
        self.workflow_id = workflow_id

    async def validate(self, args: dict) -> tuple[dict | None, str | None]:
        return (
            None,
            (
                f"工作流 {self.workflow_id} 不是 v2mini 内置工作流。"
                "自定义工作流导入将在 M2 提供；当前请使用 local/anima-txt2img-* 系列。"
            ),
        )

    async def submit(self, args: dict, args_dir: Path) -> tuple[str, Path]:
        raise NotImplementedError("GenericInjector arrives in M2")
