"""Pydantic schema for application settings.

All settings are typed. The same schema validates what comes off disk
and what arrives over the wire via ``PUT /api/settings``.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ServerSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8787


class ComfyUISettings(BaseModel):
    """Where v2mini skills live and where ComfyUI's config file is.

    The skills_root must contain ``comfyui-animatool/``, ``danbooru-tags/``,
    and ``comfyui-manager/`` (as the v2mini README requires).
    """

    skills_root: str = ""
    workspace: str = ""
    config_json: str = ""


class LLMSettings(BaseModel):
    """OpenAI-compatible LLM provider.

    ``base_url`` accepts any OpenAI-compatible endpoint:
      - OpenAI:      https://api.openai.com/v1
      - DeepSeek:    https://api.deepseek.com/v1
      - 通义千问:      https://dashscope.aliyuncs.com/compatible-mode/v1
      - Ollama:      http://127.0.0.1:11434/v1
      - LM Studio:   http://127.0.0.1:1234/v1
    """

    base_url: str = "https://api.deepseek.com/v1"
    api_key: str = ""
    model: str = "deepseek-chat"
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, ge=512, le=8192)
    # Reasoning effort: only meaningful for models that support extended
    # thinking (Claude, DeepSeek-R1, etc.). Silently ignored otherwise.
    reasoning_effort: Literal["off", "low", "medium", "high"] = "off"
    # How many recent message turns to include in LLM context.
    context_window: int = Field(default=5, ge=0, le=50)


class StorageSettings(BaseModel):
    db_path: str = "backend/runtime/chat.db"
    outputs_dir: str = "backend/runtime/outputs"


class SystemPromptSettings(BaseModel):
    v2mini_animatool_path: str = "{skills_root}/comfyui-animatool/SKILL.md"
    v2mini_danbooru_path: str = "{skills_root}/danbooru-tags/SKILL.md"
    v2mini_manager_path: str = "{skills_root}/comfyui-manager/SKILL.md"


class Settings(BaseModel):
    """Top-level settings object.

    JSON shape::

        {
          "server": {...},
          "comfyui": {...},
          "llm": {...},
          "storage": {...},
          "system_prompt": {...}
        }
    """

    server: ServerSettings = Field(default_factory=ServerSettings)
    comfyui: ComfyUISettings = Field(default_factory=ComfyUISettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    system_prompt: SystemPromptSettings = Field(default_factory=SystemPromptSettings)