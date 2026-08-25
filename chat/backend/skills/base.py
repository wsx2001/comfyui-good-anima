"""Skill bridge contracts and shared types.

M1 uses only the v2mini path (V2MiniInjector). GenericInjector arrives in
M2 for user-imported workflows.
"""
from __future__ import annotations

from enum import Enum


class JobState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATES = {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED}


class SkillError(RuntimeError):
    """Raised when a v2mini skill invocation fails."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message