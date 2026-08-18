"""Introspection and notification tools."""

from __future__ import annotations

from .. import client
from .._env import HerdrEnv
from ._base import READ_TIMEOUT, TRIVIAL_TIMEOUT, json_result, require_str, result, tool


def build_tools(env: HerdrEnv) -> list:
    async def _snapshot(arguments, signal):
        del arguments, signal
        payload = await client.request(
            env.socket_path, "session.snapshot", {}, timeout=READ_TIMEOUT
        )
        snapshot = (
            payload.get("snapshot")
            if isinstance(payload.get("snapshot"), dict)
            else payload
        )
        counts = {
            key: len(snapshot[key])
            for key in ("workspaces", "tabs", "panes", "agents")
            if isinstance(snapshot.get(key), list)
        }
        summary = ", ".join(f"{n} {k}" for k, n in counts.items()) or "snapshot"
        return json_result(snapshot, text=f"Live herdr session: {summary}")

    async def _notify(arguments, signal):
        del signal
        params: dict[str, object] = {"title": require_str(arguments, "title")}
        if arguments.get("body") is not None:
            params["body"] = str(arguments["body"])
        if arguments.get("sound") is not None:
            params["sound"] = str(arguments["sound"])
        await client.request(
            env.socket_path, "notification.show", params, timeout=TRIVIAL_TIMEOUT
        )
        return result("Notification shown")

    return [
        tool(
            "herdr_api_snapshot",
            "Dump herdr's live session state (workspaces, tabs, panes, agents).",
            {},
            _snapshot,
        ),
        tool(
            "herdr_notify",
            "Show a herdr notification to the user (e.g. when a long "
            "orchestration finishes).",
            {
                "title": {"type": "string"},
                "body": {"type": "string"},
                "sound": {"type": "string", "enum": ["none", "done", "request"]},
            },
            _notify,
            required=("title",),
        ),
    ]
