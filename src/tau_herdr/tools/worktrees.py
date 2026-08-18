"""Git worktree tools: parallel checkouts as herdr workspaces."""

from __future__ import annotations

from .. import client
from .._env import HerdrEnv
from ._base import json_result, opt, require_str, tool

_LIST_TIMEOUT = 30.0
_CREATE_TIMEOUT = 60.0


def build_tools(env: HerdrEnv) -> list:
    async def _create(arguments, signal):
        del signal
        params = opt(
            arguments, "cwd", "branch", "base", "path", "label", "workspace_id"
        ) | {"focus": bool(arguments.get("focus", False))}
        payload = await client.request(
            env.socket_path, "worktree.create", params, timeout=_CREATE_TIMEOUT
        )
        return json_result(payload)

    async def _open(arguments, signal):
        del signal
        params = opt(arguments, "cwd", "branch", "path", "label", "workspace_id") | {
            "focus": bool(arguments.get("focus", False))
        }
        payload = await client.request(
            env.socket_path, "worktree.open", params, timeout=_LIST_TIMEOUT
        )
        return json_result(payload)

    async def _list(arguments, signal):
        del signal
        payload = await client.request(
            env.socket_path,
            "worktree.list",
            opt(arguments, "cwd", "workspace_id"),
            timeout=_LIST_TIMEOUT,
        )
        return json_result(payload)

    async def _remove(arguments, signal):
        del signal
        payload = await client.request(
            env.socket_path,
            "worktree.remove",
            {
                "workspace_id": require_str(arguments, "workspace_id"),
                "force": bool(arguments.get("force", False)),
            },
            timeout=_LIST_TIMEOUT,
        )
        return json_result(payload)

    common = {
        "cwd": {"type": "string", "description": "Repository to act on."},
        "label": {"type": "string"},
        "workspace_id": {"type": "string"},
        "focus": {"type": "boolean"},
    }
    return [
        tool(
            "herdr_worktree_create",
            "Create a git worktree and open it as a herdr workspace. The result "
            "includes the new workspace and root pane, ready for "
            "herdr_start_agent.",
            common
            | {
                "branch": {"type": "string", "description": "Branch to create."},
                "base": {"type": "string", "description": "Base ref."},
                "path": {"type": "string", "description": "Checkout path."},
            },
            _create,
        ),
        tool(
            "herdr_worktree_open",
            "Open an existing git worktree as a herdr workspace.",
            common
            | {
                "branch": {"type": "string"},
                "path": {"type": "string"},
            },
            _open,
        ),
        tool(
            "herdr_worktree_list",
            "List git worktrees herdr knows about for a repository.",
            {
                "cwd": {"type": "string"},
                "workspace_id": {"type": "string"},
            },
            _list,
        ),
        tool(
            "herdr_worktree_remove",
            "Remove a worktree's herdr workspace and delete the checkout.",
            {
                "workspace_id": {"type": "string"},
                "force": {
                    "type": "boolean",
                    "description": "Remove even with uncommitted changes.",
                },
            },
            _remove,
            required=("workspace_id",),
        ),
    ]
