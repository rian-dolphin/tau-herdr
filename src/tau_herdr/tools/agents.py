"""Orchestration tools: spawn, prompt, wait on, and read herdr agents."""

from __future__ import annotations

import asyncio
import shlex
import re
import time

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
    resolve_pane_id,
    result,
    tool,
)

_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_READ_SOURCES = {
    "visible": "visible",
    "recent": "recent",
    "recent-unwrapped": "recent_unwrapped",
}
_START_BUSY_RETRY_S = 6.0

_TARGET = {
    "type": "string",
    "description": "Pane id (like w1:p3), agent name, or agent label.",
}

_AGENT_SUMMARY_FIELDS = (
    "pane_id",
    "name",
    "agent",
    "agent_status",
    "cwd",
    "tab_id",
    "workspace_id",
    "focused",
)


def _agent_summary(agent: object) -> dict[str, object]:
    if not isinstance(agent, dict):
        return {}
    return {k: agent[k] for k in _AGENT_SUMMARY_FIELDS if k in agent}


async def start_agent(env: HerdrEnv, arguments, signal) -> dict[str, object]:
    """Split a pane and start an agent in it; shared with herdr_delegate.

    Returns `{"pane_id": ..., "name": ..., "kind": ...}`.
    """
    del signal
    kind = require_str(arguments, "kind").lower()
    name = str(arguments.get("name") or "")
    if name and not _NAME.match(name):
        raise ValueError(
            "'name' must be lowercase letters, digits, '-' or '_' (herdr rejects uppercase)"
        )
    split_params: dict[str, object] = {
        "direction": arguments.get("direction") or "right",
        **opt(arguments, "cwd", "env", "workspace_id", "target_pane_id"),
        "focus": bool(arguments.get("focus", False)),
    }
    split = await client.request(
        env.socket_path, "pane.split", split_params, timeout=READ_TIMEOUT
    )
    pane = split.get("pane") if isinstance(split.get("pane"), dict) else {}
    pane_id = pane.get("pane_id")
    if not isinstance(pane_id, str):
        raise ValueError("pane.split did not return a pane id")

    args = arguments.get("args")
    args = [str(a) for a in args] if isinstance(args, list) else []
    if kind == "tau":
        # herdr has no `tau` agent kind; type the command into the new
        # pane and let tau's own self-report make it visible.
        command = shlex.join(["tau", *args])
        await client.request(
            env.socket_path,
            "pane.send_input",
            {"pane_id": pane_id, "text": command, "keys": ["Enter"]},
            timeout=TRIVIAL_TIMEOUT,
        )
        return {"pane_id": pane_id, "name": name or None, "kind": kind}

    timeout_ms = int(arguments.get("timeout_ms") or 30000)
    start_params: dict[str, object] = {
        "name": name or kind,
        "kind": kind,
        "pane_id": pane_id,
        "timeout_ms": timeout_ms,
    }
    if args:
        start_params["args"] = args
    deadline = time.monotonic() + _START_BUSY_RETRY_S
    while True:
        try:
            started = await client.request(
                env.socket_path,
                "agent.start",
                start_params,
                timeout=timeout_ms / 1000 + TRIVIAL_TIMEOUT,
            )
            break
        except client.HerdrError as error:
            # A freshly split shell may not be at a prompt yet.
            if error.code == "agent_pane_busy" and time.monotonic() < deadline:
                await asyncio.sleep(0.25)
                continue
            raise
    summary = _agent_summary(started.get("agent"))
    return {"pane_id": pane_id, "name": start_params["name"], "kind": kind, **summary}


def build_tools(env: HerdrEnv) -> list:
    async def _start(arguments, signal):
        info = await start_agent(env, arguments, signal)
        note = (
            " (tau panes appear in herdr once their self-report lands)"
            if info["kind"] == "tau"
            else ""
        )
        return json_result(
            info, text=f"Started {info['kind']} agent in pane {info['pane_id']}{note}"
        )

    async def _send_prompt(arguments, signal):
        del signal
        target = require_str(arguments, "target")
        text = require_str(arguments, "text")
        if arguments.get("submit", True):
            await client.request(
                env.socket_path,
                "agent.prompt",
                {"target": target, "text": text},
                timeout=TRIVIAL_TIMEOUT,
            )
            return result(f"Prompt submitted to {target}")
        pane_id = await resolve_pane_id(env, target)
        await client.request(
            env.socket_path,
            "pane.send_text",
            {"pane_id": pane_id, "text": text},
            timeout=TRIVIAL_TIMEOUT,
        )
        return result(f"Text typed into {target} (not submitted)")

    async def _wait(arguments, signal):
        target = require_str(arguments, "target")
        params: dict[str, object] = {"target": target}
        until = arguments.get("until")
        if isinstance(until, list) and until:
            params["until"] = [str(u) for u in until]
        timeout_ms = int(arguments.get("timeout_ms") or 60000)
        payload = await chunked_wait(
            env, "agent.wait", params, timeout_ms=timeout_ms, signal=signal
        )
        if payload is None:
            status = "unknown"
            try:
                info = await client.request(
                    env.socket_path,
                    "agent.get",
                    {"target": target},
                    timeout=TRIVIAL_TIMEOUT,
                )
                status = str(_agent_summary(info.get("agent")).get("agent_status"))
            except client.HerdrError:
                pass
            raise ValueError(
                f"timed out after {timeout_ms}ms waiting for {target} "
                f"(current status: {status})"
            )
        summary = _agent_summary(payload.get("agent"))
        return json_result(
            summary,
            text=f"{target} reached status {summary.get('agent_status', 'unknown')}",
        )

    async def _read(arguments, signal):
        del signal
        target = require_str(arguments, "target")
        source = str(arguments.get("source") or "recent")
        if source not in _READ_SOURCES:
            raise ValueError(f"'source' must be one of {sorted(_READ_SOURCES)}")
        payload = await client.request(
            env.socket_path,
            "agent.read",
            {
                "target": target,
                "source": _READ_SOURCES[source],
                "lines": int(arguments.get("lines") or 50),
                "format": "text",
            },
            timeout=READ_TIMEOUT,
        )
        read = payload.get("read") if isinstance(payload.get("read"), dict) else {}
        return result(str(read.get("text", "")))

    async def _list(arguments, signal):
        del arguments, signal
        payload = await client.request(
            env.socket_path, "agent.list", {}, timeout=TRIVIAL_TIMEOUT
        )
        agents = payload.get("agents")
        summaries = [
            _agent_summary(a) for a in (agents if isinstance(agents, list) else [])
        ]
        return json_result(summaries)

    async def _get(arguments, signal):
        del signal
        payload = await client.request(
            env.socket_path,
            "agent.get",
            {"target": require_str(arguments, "target")},
            timeout=TRIVIAL_TIMEOUT,
        )
        return json_result(_agent_summary(payload.get("agent")))

    async def _rename(arguments, signal):
        del signal
        target = require_str(arguments, "target")
        name = arguments.get("name")
        await client.request(
            env.socket_path,
            "agent.rename",
            {"target": target, "name": name if isinstance(name, str) else None},
            timeout=TRIVIAL_TIMEOUT,
        )
        return result(f"Renamed {target}" if name else f"Cleared name of {target}")

    async def _focus(arguments, signal):
        del signal
        target = require_str(arguments, "target")
        await client.request(
            env.socket_path, "agent.focus", {"target": target}, timeout=TRIVIAL_TIMEOUT
        )
        return result(f"Focused {target}")

    async def _close(arguments, signal):
        del signal
        target = require_str(arguments, "target")
        pane_id = await resolve_pane_id(env, target)
        await client.request(
            env.socket_path, "pane.close", {"pane_id": pane_id}, timeout=TRIVIAL_TIMEOUT
        )
        return result(f"Closed pane {pane_id}")

    return [
        tool(
            "herdr_start_agent",
            "Split a new herdr pane and start a coding agent in it. Known kinds "
            "include claude, codex, gemini, opencode, pi, and tau (the herdr "
            "server validates the kind; tau panes are started by typing the "
            "command and become visible via self-report).",
            {
                "kind": {"type": "string", "description": "Agent kind, e.g. claude, tau."},
                "name": {
                    "type": "string",
                    "description": "Lowercase agent name for later targeting.",
                },
                "cwd": {"type": "string"},
                "direction": {"type": "string", "enum": ["right", "down"]},
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Extra CLI arguments for the agent command.",
                },
                "env": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "Extra environment variables for the pane.",
                },
                "workspace_id": {"type": "string"},
                "target_pane_id": {
                    "type": "string",
                    "description": "Pane to split (default: the current pane).",
                },
                "focus": {"type": "boolean"},
                "timeout_ms": {
                    "type": "integer",
                    "description": "Agent startup timeout (default 30000).",
                },
            },
            _start,
            required=("kind",),
        ),
        tool(
            "herdr_send_prompt",
            "Send a prompt to a herdr agent. submit=true (default) submits it; "
            "submit=false only types the text.",
            {
                "target": _TARGET,
                "text": {"type": "string"},
                "submit": {"type": "boolean"},
            },
            _send_prompt,
            required=("target", "text"),
        ),
        tool(
            "herdr_wait_agent",
            "Wait until a herdr agent reaches a status (default: idle, done, or "
            "blocked). Errors on timeout with the current status.",
            {
                "target": _TARGET,
                "until": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["idle", "working", "blocked", "done", "unknown"],
                    },
                },
                "timeout_ms": {
                    "type": "integer",
                    "description": "Overall wait budget (default 60000).",
                },
            },
            _wait,
            required=("target",),
        ),
        tool(
            "herdr_read_agent",
            "Read the terminal output of a herdr agent pane.",
            {
                "target": _TARGET,
                "source": {
                    "type": "string",
                    "enum": ["visible", "recent", "recent-unwrapped"],
                    "description": "Default: recent.",
                },
                "lines": {"type": "integer", "description": "Default 50."},
            },
            _read,
            required=("target",),
        ),
        tool(
            "herdr_list_agents",
            "List all agents herdr knows about, with pane ids and statuses.",
            {},
            _list,
        ),
        tool(
            "herdr_get_agent",
            "Show one herdr agent's pane id, status, cwd, and location.",
            {"target": _TARGET},
            _get,
            required=("target",),
        ),
        tool(
            "herdr_rename_agent",
            "Rename a herdr agent (lowercase); omit 'name' to clear the name.",
            {"target": _TARGET, "name": {"type": "string"}},
            _rename,
            required=("target",),
        ),
        tool(
            "herdr_focus_agent",
            "Focus a herdr agent's pane in the user's terminal.",
            {"target": _TARGET},
            _focus,
            required=("target",),
        ),
        tool(
            "herdr_close_pane",
            "Close a herdr pane (accepts a pane id or an agent target). This "
            "kills whatever runs in it.",
            {"target": _TARGET},
            _close,
            required=("target",),
        ),
    ]
