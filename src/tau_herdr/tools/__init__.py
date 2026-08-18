"""The LLM-facing herdr tool surface (see dev-notes/spec-v02.md)."""

from __future__ import annotations

from .._env import HerdrEnv
from . import agents, delegate, layout, misc, sync, worktrees

PROMPT_GUIDELINE = (
    "You run inside a herdr workspace. Use the herdr_* tools to spawn and "
    "coordinate other coding agents in panes, run commands in separate "
    "terminals, create git worktrees for parallel work, and notify the user "
    "when long orchestrations finish. Prefer herdr_delegate for one-shot "
    "subtasks."
)


def build_all_tools(env: HerdrEnv) -> list:
    tools = []
    for module in (agents, delegate, sync, layout, worktrees, misc):
        tools.extend(module.build_tools(env))
    return tools
