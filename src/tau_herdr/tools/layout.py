"""The herdr_layout multiplexer: panes, tabs, and workspaces (ADR 0003)."""

from __future__ import annotations

from collections.abc import Mapping

from .. import client
from .._env import HerdrEnv
from ._base import READ_TIMEOUT, TRIVIAL_TIMEOUT, json_result, opt, require_str, tool

# action -> (method, required argument names, param builder)
_ACTIONS: dict[str, object] = {}


def _action(name):
    def register(fn):
        _ACTIONS[name] = fn
        return fn

    return register


@_action("list_panes")
def _list_panes(a: Mapping[str, object]) -> tuple[str, dict[str, object]]:
    return "pane.list", opt(a, "workspace_id")


@_action("get_pane")
def _get_pane(a):
    return "pane.get", {"pane_id": require_str(a, "pane_id")}


@_action("move_pane")
def _move_pane(a):
    destination = a.get("destination")
    if not isinstance(destination, dict) or "type" not in destination:
        raise ValueError(
            "move_pane needs 'destination', e.g. "
            '{"type": "tab", "tab_id": "w1:t2", "split": "right"}, '
            '{"type": "new_tab"}, or {"type": "new_workspace"}'
        )
    return "pane.move", {
        "pane_id": require_str(a, "pane_id"),
        "destination": destination,
        "focus": bool(a.get("focus", False)),
    }


@_action("list_tabs")
def _list_tabs(a):
    return "tab.list", opt(a, "workspace_id")


@_action("create_tab")
def _create_tab(a):
    return "tab.create", opt(a, "cwd", "label", "workspace_id") | {
        "focus": bool(a.get("focus", False))
    }


@_action("focus_tab")
def _focus_tab(a):
    return "tab.focus", {"tab_id": require_str(a, "tab_id")}


@_action("rename_tab")
def _rename_tab(a):
    return "tab.rename", {
        "tab_id": require_str(a, "tab_id"),
        "label": require_str(a, "label"),
    }


@_action("close_tab")
def _close_tab(a):
    return "tab.close", {"tab_id": require_str(a, "tab_id")}


@_action("list_workspaces")
def _list_workspaces(a):
    return "workspace.list", {}


@_action("create_workspace")
def _create_workspace(a):
    return "workspace.create", opt(a, "cwd", "label") | {
        "focus": bool(a.get("focus", False))
    }


@_action("focus_workspace")
def _focus_workspace(a):
    return "workspace.focus", {"workspace_id": require_str(a, "workspace_id")}


@_action("rename_workspace")
def _rename_workspace(a):
    return "workspace.rename", {
        "workspace_id": require_str(a, "workspace_id"),
        "label": require_str(a, "label"),
    }


@_action("close_workspace")
def _close_workspace(a):
    return "workspace.close", {"workspace_id": require_str(a, "workspace_id")}


def build_tools(env: HerdrEnv) -> list:
    async def _layout(arguments, signal):
        del signal
        action = require_str(arguments, "action")
        builder = _ACTIONS.get(action)
        if builder is None:
            raise ValueError(f"unknown action; use one of {sorted(_ACTIONS)}")
        method, params = builder(arguments)
        payload = await client.request(
            env.socket_path,
            method,
            params,
            timeout=READ_TIMEOUT if action.startswith("create") else TRIVIAL_TIMEOUT,
        )
        return json_result(payload)

    return [
        tool(
            "herdr_layout",
            "Inspect and manage herdr layout. Actions: "
            + ", ".join(sorted(_ACTIONS))
            + ". move_pane takes a 'destination' object "
            '({"type": "tab"|"new_tab"|"new_workspace", ...}).',
            {
                "action": {"type": "string", "enum": sorted(_ACTIONS)},
                "pane_id": {"type": "string"},
                "tab_id": {"type": "string"},
                "workspace_id": {"type": "string"},
                "label": {"type": "string"},
                "cwd": {"type": "string"},
                "focus": {"type": "boolean"},
                "destination": {
                    "type": "object",
                    "description": "move_pane only; see the tool description.",
                },
            },
            _layout,
            required=("action",),
        )
    ]
