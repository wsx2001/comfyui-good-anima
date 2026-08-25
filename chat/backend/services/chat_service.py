"""Chat service — executes LLM tool calls.

All three tools are live as of Step 4:
  - submit_image_gen   → job_service (single ComfyUI job, awaited inline)
  - enqueue_scene_list → job_queue  (serial queue + worker task)
  - validate_tags      → danbooru CLI

The executor is called from the SSE stream loop in api/messages.py when
the parser reports a completed tool call. Results are returned as a dict
that the caller serialises into the tool-result message for the next LLM
turn (multi-turn tool use).
"""
from __future__ import annotations

import json
from typing import Any, Optional

from backend.skills.danbooru import validate_hard_tags
from backend.services import job_queue, job_service
from backend.utils.log import get_logger

logger = get_logger()

MAX_TOOL_ROUNDS = 4  # safety cap on multi-turn tool use per user message


async def execute_tool(
    name: str,
    arguments: dict,
    conversation_id: str,
    assistant_message_id: str | None,
) -> dict:
    """Run one tool call. Returns a JSON-serialisable result dict.

    Shape: {"ok": bool, ...result-or-error}. The "ok" key lets the LLM
    branch on failure without parsing nested error formats.
    """
    if name == "submit_image_gen":
        return await _submit_image_gen(arguments, conversation_id, assistant_message_id)
    if name == "validate_tags":
        return await _validate_tags(arguments)
    if name == "enqueue_scene_list":
        return await _enqueue_scene_list(arguments, conversation_id)
    return {"ok": False, "error": f"未知工具：{name}"}


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def _submit_image_gen(
    arguments: dict,
    conversation_id: str,
    assistant_message_id: str | None,
) -> dict:
    workflow_id = str(arguments.get("workflow_id") or "")
    args = arguments.get("args")
    scene_label = arguments.get("scene_label")

    if not workflow_id:
        return {"ok": False, "error": "缺少 workflow_id"}
    if not isinstance(args, dict):
        return {"ok": False, "error": "args 必须是对象"}

    job, err = await job_service.create_and_submit(
        conversation_id=conversation_id,
        message_id=assistant_message_id,
        workflow_id=workflow_id,
        args=args,
        source="single",
    )
    if err or job is None:
        return {"ok": False, "error": err}

    payload: dict[str, Any] = {
        "ok": True,
        "job_id": job.id,
        "workflow_id": job.workflow_id,
        "seed": json.loads(job.args_snapshot).get("seed"),
        "state": job.state,
    }
    if scene_label:
        payload["scene_label"] = scene_label

    # Block until terminal so the LLM's summary can reference the outcome.
    await job_service.wait_for_job(job.id)
    final_state, images = job_service.job_snapshot(job.id)
    payload["final_state"] = final_state
    payload["images"] = images
    if final_state != "succeeded":
        payload["ok"] = False
        payload["error"] = f"生图未成功（状态 {final_state}）"

    return payload


async def _enqueue_scene_list(arguments: dict, conversation_id: str) -> dict:
    workflow_id = str(arguments.get("workflow_id") or "")
    items = arguments.get("items")
    title = str(arguments.get("title") or "场景队列")

    if not workflow_id:
        return {"ok": False, "error": "缺少 workflow_id"}
    if not isinstance(items, list) or not items:
        return {"ok": False, "error": "items 必须是非空数组"}

    queue_id, err = await job_queue.create_queue(
        conversation_id=conversation_id,
        workflow_id=workflow_id,
        title=title[:64],
        items=items,
    )
    if err or queue_id is None:
        return {"ok": False, "error": err}

    logger.info("queue {} created via tool ({} items)", queue_id, len(items))
    return {
        "ok": True,
        "queue_id": queue_id,
        "item_count": len(items),
        "note": (
            "队列已创建并开始串行执行。每完成一项会自动把图片插入对话流；"
            "用户可在队列面板暂停/恢复/取消或追加新场景。"
        ),
    }


async def _validate_tags(arguments: dict) -> dict:
    candidates = arguments.get("candidates")
    group = str(arguments.get("group") or "general")

    if not isinstance(candidates, list) or not candidates:
        return {"ok": False, "error": "candidates 必须是非空数组"}
    candidates = [str(c) for c in candidates[:16]]  # cap batch size

    result = await validate_hard_tags(candidates, group=group)
    if result.get("error"):
        return {"ok": False, "error": result["error"]}
    return {
        "ok": True,
        "confirmed": result["confirmed"],
        "unknown": result["unknown"],
    }