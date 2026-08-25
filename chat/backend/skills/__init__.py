"""Skill bridge package.

Exposes the injector factory as the primary entry point.
"""
from backend.skills.base import JobState, SkillError, TERMINAL_STATES
from backend.skills.workflow_injector import get_injector, is_v2mini

__all__ = ["JobState", "SkillError", "TERMINAL_STATES", "get_injector", "is_v2mini"]