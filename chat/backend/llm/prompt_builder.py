"""Assemble the system prompt sent to the LLM.

Reads the three v2mini SKILL.md files from disk on first call, caches
the result, and re-reads when the caller asks (e.g. after settings change).

The cached prompt is keyed by file mtime so changes to SKILL.md are
detected automatically on the next call.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from backend.config.loader import get_config
from backend.utils.log import get_logger

logger = get_logger()

# ---------------------------------------------------------------------------
# Static blocks (independent of skills_root)
# ---------------------------------------------------------------------------

_ROLE_BLOCK = """# Role

你是 Good Anima Chat 的生图助理。用户的请求经由 v2mini 技能链路由给 ComfyUI 执行。
你的职责：

1. 理解用户的画面意图（角色、画师、构图、情绪）。
2. 在 system prompt 列出的硬约束范围内自由创作。
3. 输出符合下层工作流要求的结构化 prompt。
4. 通过 tool call 提交生图请求，**绝不**直接执行 ComfyUI 内部细节。"""


_WORKFLOW_DECISION_TREE = """# Workflow Decision Tree

| 用户意图                                | 你的动作                                            |
| --------------------------------------- | --------------------------------------------------- |
| 普通生图（一句画面描述）                | 视觉简报 → tag 校验（仅 hard_tags）→ 三层 prompt → submit_image_gen |
| 「依次生成 N 个场景」「按这个列表生图」 | 拆解为独立 prompt 列表 → **enqueue_scene_list**     |
| 「用 X workflow 出图」「切到 base」     | workflow_id 字段显式变化 → submit_image_gen         |
| 迭代微调（「刚才那张再忧郁一点」）      | 接收上一轮 prompt 作为上下文 → submit_image_gen     |
| 参数调整（"出 4 张"、"16:9 横构图"）  | 直接修改 args 字段 → submit_image_gen               |
| 「抽卡」「随机画师」                    | submit_image_gen 中只设 batch_size，由工作流抽卡    |
| 仅查 tag/画师（用户没说生图）          | 仅输出自然语言回答；不调用任何 tool                  |

注意：「依次生成」= 多张**不同**画面，必须用 **enqueue_scene_list**，**不是** batch_size。
batch_size 只用于同一画面的姿势/构图抽卡。"""


_AVAILABLE_WORKFLOWS_HINT = """# Available Workflows

工具调用 `submit_image_gen(workflow_id=...)` 中的 workflow_id 取自用户配置 + 上方 SKILL 中
v2mini 内置的 5 个 workflow。前端 UI 通常会显式选择 workflow；用户没指定时用会话默认值
（conversation.default_workflow_id）。"""


_OUTPUT_FORMAT = """# Output Format

- 默认自然语言回复用 Markdown，简洁、不堆砌。
- 触发生图时**必须**调用 `submit_image_gen` tool，args 必须含完整 prompt_11 / prompt_12。
- 触发队列时**必须**调用 `enqueue_scene_list` tool，items 数组每个元素独立 prompt。
- **不要**直接告诉用户 prompt_id、args 等内部字段；前端会自动展示。
- 不要重复用户已经说过的内容。"""


def _list_workflows_hint() -> str:
    """Return a short list of workflow names for the system prompt.

    Step 2: hard-coded v2mini defaults. Step 9 (custom workflows) will
    append user-imported ones at runtime.
    """
    return (
        "- local/anima-txt2img-aesthetic-lora（**默认**，双 LoRA + TeaCache + RTX VSR 2x）\n"
        "- local/anima-txt2img-aesthetic-lora-artist-mixer（画师融合，明确说融合时用）\n"
        "- local/anima-txt2img-aesthetic-lora-enhancer（加速版，约 30% 提速，有锐化副作用）\n"
        "- local/anima-txt2img-aesthetic-lora-fixed（固定参数版）\n"
        "- local/anima-txt2img-base（裸模型，对比测试用）"
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("SKILL.md not found: {}", path)
        return ""
    except Exception as exc:
        logger.error("Failed to read {}: {}", path, exc)
        return ""


def _render_paths() -> dict[str, Path]:
    """Resolve template paths like ``{skills_root}/...`` from the current config."""
    cfg = get_config()
    root = cfg.comfyui.skills_root
    if not root:
        return {}
    base = Path(root)
    return {
        "animatool": base / "comfyui-animatool" / "SKILL.md",
        "danbooru": base / "danbooru-tags" / "SKILL.md",
        "manager": base / "comfyui-manager" / "SKILL.md",
    }


def build_system_prompt() -> str:
    """Compose the full system prompt.

    Sections (in order):
      1. Role
      2. Hard Constraints (verbatim from v2mini SKILL.md files, truncated)
      3. Workflow Decision Tree
      4. Available Workflows (dynamic)
      5. Available Tools (handled by OpenAI tool= parameter, not text)
      6. Output Format

    The full v2mini SKILL.md files are large (~600 lines combined). We
    pass them through verbatim — LLM context budget is 4k– tokens and
    the rules need exact phrasing. Step 3 may add selective excerpt.
    """
    paths = _render_paths()
    animatool_text = _read_text(paths["animatool"]) if "animatool" in paths else ""
    danbooru_text = _read_text(paths["danbooru"]) if "danbooru" in paths else ""
    manager_text = _read_text(paths["manager"]) if "manager" in paths else ""

    if not (animatool_text or danbooru_text or manager_text):
        logger.warning(
            "No v2mini SKILL.md files loaded; check comfyui.skills_root in Settings. "
            "Falling back to a minimal prompt — the LLM will lack hard constraints."
        )

    parts = [
        _ROLE_BLOCK,
        "# Hard Constraints (v2mini)",
        animatool_text or "(comfyui-animatool/SKILL.md 缺失，请设置 skills_root)",
        danbooru_text or "(danbooru-tags/SKILL.md 缺失)",
        manager_text or "(comfyui-manager/SKILL.md 缺失)",
        _WORKFLOW_DECISION_TREE,
        "# Available Workflows",
        _list_workflows_hint(),
        _AVAILABLE_WORKFLOWS_HINT,
        _OUTPUT_FORMAT,
    ]
    return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# Cache keyed by mtime of the three SKILL.md files
# ---------------------------------------------------------------------------

_cached: Optional[str] = None
_cached_signature: tuple = ()


def get_cached_system_prompt() -> str:
    """Return the cached system prompt, rebuilding when SKILL.md files change."""
    global _cached, _cached_signature

    paths = _render_paths()
    signature = tuple(
        (p.stat().st_mtime_ns if p.exists() else 0) for p in paths.values()
    ) if paths else ()

    if _cached is None or signature != _cached_signature:
        _cached = build_system_prompt()
        _cached_signature = signature
        logger.info("System prompt rebuilt ({} chars)", len(_cached))
    return _cached


def invalidate_cache() -> None:
    """Force next get_cached_system_prompt() to rebuild."""
    global _cached, _cached_signature
    _cached = None
    _cached_signature = ()