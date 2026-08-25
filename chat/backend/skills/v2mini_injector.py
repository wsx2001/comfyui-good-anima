"""V2Mini injector — the five built-in ``local/anima-*`` workflows.

Submission path (TECH §7):
    validate_args → write args.json → node run_workflow_args.js submit

The workflow_id must be one of the five known IDs; anything else falls
through to GenericInjector via the factory in ``workflow_injector.py``.
"""
from __future__ import annotations

import random
from pathlib import Path

from backend.skills.comfyui import submit_workflow
from backend.skills.prompts import validate_args
from backend.utils.log import get_logger

logger = get_logger()

# The five v2mini built-ins (comfyui-manager/SKILL.md §3).
# Keys are what the LLM may use; values are canonical workflow IDs.
WORKFLOW_ALIASES = {
    "local/anima-txt2img-aesthetic-lora": "local/anima-txt2img-aesthetic-lora",
    "anima-txt2img-aesthetic-lora": "local/anima-txt2img-aesthetic-lora",
    "aesthetic-lora": "local/anima-txt2img-aesthetic-lora",
    "default": "local/anima-txt2img-aesthetic-lora",
    "local/anima-txt2img-base": "local/anima-txt2img-base",
    "base": "local/anima-txt2img-base",
    "local/anima-txt2img-aesthetic-lora-artist-mixer": "local/anima-txt2img-aesthetic-lora-artist-mixer",
    "artist-mixer": "local/anima-txt2img-aesthetic-lora-artist-mixer",
    "mixer": "local/anima-txt2img-aesthetic-lora-artist-mixer",
    "local/anima-txt2img-aesthetic-lora-enhancer": "local/anima-txt2img-aesthetic-lora-enhancer",
    "enhancer": "local/anima-txt2img-aesthetic-lora-enhancer",
    "local/anima-txt2img-aesthetic-lora-fixed": "local/anima-txt2img-aesthetic-lora-fixed",
    "fixed": "local/anima-txt2img-aesthetic-lora-fixed",
}

V2MINI_WORKFLOWS = set(WORKFLOW_ALIASES.values())


def normalize_workflow_id(workflow_id: str) -> str:
    """Map aliases/short names to canonical ``local/...`` form."""
    return WORKFLOW_ALIASES.get(workflow_id, workflow_id)


class V2MiniInjector:
    mode = "v2mini"

    def __init__(self, workflow_id: str):
        self.workflow_id = normalize_workflow_id(workflow_id)

    async def validate(self, args: dict) -> tuple[dict | None, str | None]:
        """Validate + normalize args. Seed is generated when absent."""
        normalized, error = validate_args(args)
        if error or normalized is None:
            return None, error
        data = normalized.model_dump()

        # run_workflow_args.js auto-generates a seed when omitted, but we
        # generate here so the seed is recorded in args_snapshot / Image rows.
        if data.get("seed") is None:
            data["seed"] = random.randint(0, 2**32 - 1)
        return data, None

    async def submit(self, args: dict, args_dir: Path) -> tuple[str, Path]:
        return await submit_workflow(self.workflow_id, args, args_dir)
