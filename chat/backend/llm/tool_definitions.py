"""Tool / function-calling definitions exposed to the LLM.

We expose three tools (M1 Step 2). The LLM chooses whether to call them
based on user input + system prompt.

Step 3 will wire ``submit_image_gen`` to the ComfyUI submission path.
Step 4 will wire ``enqueue_scene_list`` to JobQueue creation.

Each tool is a dict in OpenAI's function-calling schema:
  {
    "type": "function",
    "function": {
      "name": "...",
      "description": "...",
      "parameters": { JSON Schema }
    }
  }
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# submit_image_gen
# ---------------------------------------------------------------------------

SUBMIT_IMAGE_GEN = {
    "type": "function",
    "function": {
        "name": "submit_image_gen",
        "description": (
            "向 ComfyUI 提交一次生图任务并等待完成，结果图会直接返回。"
            "适合单张生成。必须同时提供 workflow_id 与 args"
            "（含 prompt_11/prompt_12 等）。多场景串行请改用 enqueue_scene_list。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workflow_id": {
                    "type": "string",
                    "description": "工作流 ID。默认 v2mini/anima-txt2img-aesthetic-lora。",
                },
                "args": {
                    "type": "object",
                    "description": (
                        "扁平 args 对象。必须包含：prompt_11（正向 prompt）、"
                        "prompt_12（负向 prompt）、width、height、batch_size、"
                        "steps、filename_prefix。可选：seed、cfg、rtx_vsr_quality。"
                    ),
                    "properties": {
                        "prompt_11": {"type": "string", "minLength": 1},
                        "prompt_12": {"type": "string", "minLength": 1},
                        "width": {"type": "integer", "minimum": 64, "maximum": 4096},
                        "height": {"type": "integer", "minimum": 64, "maximum": 4096},
                        "batch_size": {"type": "integer", "minimum": 1, "maximum": 8},
                        "steps": {"type": "integer", "minimum": 1, "maximum": 100},
                        "cfg": {"type": "number", "minimum": 0.0, "maximum": 30.0},
                        "seed": {"type": "integer"},
                        "filename_prefix": {"type": "string", "minLength": 1, "maxLength": 64},
                        "rtx_vsr_quality": {
                            "type": "string",
                            "enum": ["OFF", "PERFORMANCE", "BALANCED", "QUALITY", "ULTRA"],
                        },
                    },
                    "required": [
                        "prompt_11",
                        "prompt_12",
                        "width",
                        "height",
                        "batch_size",
                        "steps",
                        "filename_prefix",
                    ],
                },
                "scene_label": {
                    "type": "string",
                    "description": "可选的场景标签，用于在对话中标识本次出图（如 'A 雨天天台'）。",
                },
            },
            "required": ["workflow_id", "args"],
        },
    },
}


# ---------------------------------------------------------------------------
# enqueue_scene_list
# ---------------------------------------------------------------------------

ENQUEUE_SCENE_LIST = {
    "type": "function",
    "function": {
        "name": "enqueue_scene_list",
        "description": (
            "当用户表达『依次生成 N 个场景』『按场景列表生图』等意图时使用。"
            "把场景列表转为任务队列，后台串行逐张执行；每完成一张会自动把图片插入对话流。"
            "用户可在队列面板暂停/恢复/取消，或追加新场景。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workflow_id": {
                    "type": "string",
                    "description": "整个队列使用的工作流 ID（同一队列固定）。",
                },
                "items": {
                    "type": "array",
                    "description": "场景列表。每个元素独立完成视觉简报+tag 校验+三层 prompt。",
                    "minItems": 1,
                    "maxItems": 50,
                    "items": {
                        "type": "object",
                        "properties": {
                            "scene_label": {"type": "string"},
                            "prompt_11": {"type": "string", "minLength": 1},
                            "prompt_12": {"type": "string", "minLength": 1},
                            "args": {
                                "type": "object",
                                "properties": {
                                    "width": {"type": "integer", "minimum": 64, "maximum": 4096},
                                    "height": {"type": "integer", "minimum": 64, "maximum": 4096},
                                    "steps": {"type": "integer", "minimum": 1, "maximum": 100},
                                    "cfg": {"type": "number"},
                                    "seed": {"type": "integer"},
                                    "filename_prefix": {"type": "string", "minLength": 1, "maxLength": 64},
                                    "rtx_vsr_quality": {"type": "string"},
                                },
                            },
                        },
                        "required": ["prompt_11", "prompt_12", "args"],
                    },
                },
            },
            "required": ["workflow_id", "items"],
        },
    },
}


# ---------------------------------------------------------------------------
# validate_tags
# ---------------------------------------------------------------------------

VALIDATE_TAGS = {
    "type": "function",
    "function": {
        "name": "validate_tags",
        "description": (
            "把候选 tag 列表送入 danbooru-tags 做精确校验，返回 confirmed/unknown。"
            "用于硬约束 tag（如角色、作品、画师）确认；校验失败的 tag 会从 prompt 中剔除。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "candidates": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "待校验的 tag 列表（最多 16 个）。",
                },
                "group": {
                    "type": "string",
                    "enum": ["character", "copyright", "artist", "general"],
                    "description": "按 Danbooru 分类校验。",
                },
            },
            "required": ["candidates"],
        },
    },
}


ALL_TOOLS = [SUBMIT_IMAGE_GEN, ENQUEUE_SCENE_LIST, VALIDATE_TAGS]


def tool_names() -> list[str]:
    return [t["function"]["name"] for t in ALL_TOOLS]