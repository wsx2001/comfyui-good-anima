"""Workflow injector abstraction + factory.

Two modes (TECH §7):

  v2mini  — the five built-in ``local/anima-*`` workflows. Args are the
            flat dict consumed by ``run_workflow_args.js``; validation
            enforces the full v2mini schema.
  generic — user-imported workflows with explicit prompt-node mapping.
            Placeholder in M1; full implementation lands in M2.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from backend.skills.comfyui import ComfySkillError, submit_workflow


class WorkflowInjector(Protocol):
    """Per-workflow validation + submission strategy."""

    workflow_id: str
    mode: str  # "v2mini" | "generic"

    async def validate(self, args: dict) -> tuple[dict | None, str | None]:
        """Return (normalized_args, error_message). Exactly one is non-None."""
        ...

    async def submit(self, args: dict, args_dir: Path) -> tuple[str, Path]:
        """Submit and return (prompt_id, args_file)."""
        ...


def is_v2mini(workflow_id: str) -> bool:
    from backend.skills.v2mini_injector import V2MINI_WORKFLOWS

    return workflow_id in V2MINI_WORKFLOWS


def get_injector(workflow_id: str) -> WorkflowInjector:
    if is_v2mini(workflow_id):
        from backend.skills.v2mini_injector import V2MiniInjector

        return V2MiniInjector(workflow_id)
    from backend.skills.generic_injector import GenericInjector

    return GenericInjector(workflow_id)


__all__ = ["WorkflowInjector", "get_injector", "is_v2mini", "ComfySkillError", "submit_workflow"]