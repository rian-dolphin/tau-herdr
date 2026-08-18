"""Pane-sync tools: raw terminals without an agent."""

from __future__ import annotations

from .. import client
from .._env import HerdrEnv
from ._base import (
    READ_TIMEOUT,
    TRIVIAL_TIMEOUT,
    chunked_wait,
    is_pane_id,
    json_result,
    opt,
    require_str,
    result,
    tool,
)

_READ_SOURCES = {
    "visible": "visible",
    "recent": "recent",
    "recent-unwrapped": "recent_unwrapped",
}


def build_tools(env: HerdrEnv) -> list:
    async def _split(arguments, signal):
        del signal
        params: dict[str, object] = {
            "direction": arguments.get("direction") or "right",
            **opt(arguments, "cwd", "env", "ratio", "workspace_id", "target_pane_id"),
            "focus": bool(arguments.get("focus", False)),
        }
        payload = await client.request(
            env.socket_path, "pane.split", params, timeout=READ_TIMEOUT
        )
        pane = payload.get("pane") if isinstance(payload.get("pane"), dict) else {}
        return json_result(
            {"pane_id": pane.get("pane_id"), "tab_id": pane.get("tab_id")},
            text=f"Created pane {pane.get('pane_id')}",
        )

    async def _run(arguments, signal):
        del signal
        pane_id = require_str(arguments, "pane_id")
        command = require_str(arguments, "command")
        await client.request(
            env.socket_path,
            "pane.send_input",
            {"pane_id": pane_id, "text": command, "keys": ["Enter"]},
            timeout=TRIVIAL_TIMEOUT,
        )
        return result(
            f"Command sent to {pane_id}. Use herdr_wait_output or "
            "herdr_read_pane to observe it."
        )

    async def _read(arguments, signal):
        del signal
        pane_id = require_str(arguments, "pane_id")
        source = str(arguments.get("source") or "recent")
        if source not in _READ_SOURCES:
            raise ValueError(f"'source' must be one of {sorted(_READ_SOURCES)}")
        payload = await client.request(
            env.socket_path,
            "pane.read",
            {
                "pane_id": pane_id,
                "source": _READ_SOURCES[source],
                "lines": int(arguments.get("lines") or 50),
                "format": "text",
            },
            timeout=READ_TIMEOUT,
        )
        read = payload.get("read") if isinstance(payload.get("read"), dict) else {}
        return result(str(read.get("text", "")))

    async def _wait_output(arguments, signal):
        pane_id = require_str(arguments, "pane_id")
        match = arguments.get("match")
        regex = arguments.get("regex")
        if bool(match) == bool(regex):
            raise ValueError("pass exactly one of 'match' (substring) or 'regex'")
        params: dict[str, object] = {
            "pane_id": pane_id,
            "source": _READ_SOURCES[str(arguments.get("source") or "recent")],
            "match": (
                {"type": "substring", "value": str(match)}
                if match
                else {"type": "regex", "value": str(regex)}
            ),
        }
        if arguments.get("lines") is not None:
            params["lines"] = int(arguments["lines"])
        timeout_ms = int(arguments.get("timeout_ms") or 30000)
        payload = await chunked_wait(
            env, "pane.wait_for_output", params, timeout_ms=timeout_ms, signal=signal
        )
        if payload is None:
            raise ValueError(
                f"no matching output in {pane_id} after {timeout_ms}ms"
            )
        return json_result(
            {"matched_line": payload.get("matched_line")},
            text=f"Matched: {payload.get('matched_line')}",
        )

    async def _send_keys(arguments, signal):
        del signal
        target = require_str(arguments, "target")
        keys = arguments.get("keys")
        if not isinstance(keys, list) or not keys:
            raise ValueError("'keys' must be a non-empty array")
        keys = [str(k) for k in keys]
        if is_pane_id(target):
            await client.request(
                env.socket_path,
                "pane.send_keys",
                {"pane_id": target, "keys": keys},
                timeout=TRIVIAL_TIMEOUT,
            )
        else:
            await client.request(
                env.socket_path,
                "agent.send_keys",
                {"target": target, "keys": keys},
                timeout=TRIVIAL_TIMEOUT,
            )
        return result(f"Sent {len(keys)} key(s) to {target}")

    return [
        tool(
            "herdr_split_pane",
            "Split a herdr pane and get a new shell pane.",
            {
                "direction": {"type": "string", "enum": ["right", "down"]},
                "cwd": {"type": "string"},
                "env": {"type": "object", "additionalProperties": {"type": "string"}},
                "ratio": {"type": "number"},
                "workspace_id": {"type": "string"},
                "target_pane_id": {
                    "type": "string",
                    "description": "Pane to split (default: the current pane).",
                },
                "focus": {"type": "boolean"},
            },
            _split,
        ),
        tool(
            "herdr_run_command",
            "Type a shell command into a pane and press Enter. Fire-and-forget: "
            "pair with herdr_wait_output or herdr_read_pane.",
            {
                "pane_id": {"type": "string"},
                "command": {"type": "string"},
            },
            _run,
            required=("pane_id", "command"),
        ),
        tool(
            "herdr_read_pane",
            "Read the terminal output of any herdr pane.",
            {
                "pane_id": {"type": "string"},
                "source": {
                    "type": "string",
                    "enum": ["visible", "recent", "recent-unwrapped"],
                },
                "lines": {"type": "integer", "description": "Default 50."},
            },
            _read,
            required=("pane_id",),
        ),
        tool(
            "herdr_wait_output",
            "Wait until a pane's output matches a substring or regex.",
            {
                "pane_id": {"type": "string"},
                "match": {"type": "string", "description": "Substring to wait for."},
                "regex": {"type": "string", "description": "Regex to wait for."},
                "source": {
                    "type": "string",
                    "enum": ["visible", "recent", "recent-unwrapped"],
                },
                "lines": {"type": "integer"},
                "timeout_ms": {"type": "integer", "description": "Default 30000."},
            },
            _wait_output,
            required=("pane_id",),
        ),
        tool(
            "herdr_send_keys",
            "Send key presses (e.g. Enter, Escape, C-c) to a pane or agent.",
            {
                "target": {
                    "type": "string",
                    "description": "Pane id or agent target.",
                },
                "keys": {"type": "array", "items": {"type": "string"}},
            },
            _send_keys,
            required=("target", "keys"),
        ),
    ]
