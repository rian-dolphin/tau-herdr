"""Shared helpers for the herdr tool surface."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable, Mapping

from tau_agent.messages import TextContent
from tau_agent.tools import AgentTool, AgentToolResult

from .. import client
from .._env import HerdrEnv

TRIVIAL_TIMEOUT = 10.0
READ_TIMEOUT = 15.0
WAIT_CHUNK_MS = 2000
WAIT_SLACK = 5.0

# Pane ids look like "w6H:p3"; agent names never contain ":".
_PANE_ID = re.compile(r"^[^:\s]+:p\d+$")

ToolFn = Callable[[Mapping[str, object], object], Awaitable[AgentToolResult]]


def tool(
    name: str,
    description: str,
    properties: dict[str, object],
    fn: ToolFn,
    *,
    required: tuple[str, ...] = (),
) -> AgentTool:
    """Build an AgentTool from a `(arguments, signal)` coroutine."""

    async def execute(tool_call_id, arguments, signal=None, on_update=None):
        del tool_call_id, on_update
        return await fn(arguments, signal)

    return AgentTool(
        name=name,
        label=name,
        description=description,
        parameters={
            "type": "object",
            "properties": properties,
            "required": list(required),
            "additionalProperties": False,
        },
        execute_fn=execute,
    )


def result(text: str, details: object = None) -> AgentToolResult:
    return AgentToolResult(content=[TextContent(text=text)], details=details)


def json_result(payload: object, *, text: str | None = None) -> AgentToolResult:
    return result(text if text is not None else json.dumps(payload), details=payload)


def is_pane_id(target: str) -> bool:
    return bool(_PANE_ID.match(target))


def cancelled(signal: object) -> bool:
    return signal is not None and signal.is_cancelled()


def opt(arguments: Mapping[str, object], *names: str) -> dict[str, object]:
    """Pick the named optional arguments that were actually provided."""
    return {name: arguments[name] for name in names if arguments.get(name) is not None}


def require_str(arguments: Mapping[str, object], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"'{name}' is required")
    return value


async def resolve_pane_id(env: HerdrEnv, target: str) -> str:
    """Resolve an agent name/label to its pane id; pane ids pass through."""
    if is_pane_id(target):
        return target
    info = await client.request(
        env.socket_path, "agent.get", {"target": target}, timeout=TRIVIAL_TIMEOUT
    )
    agent = info.get("agent")
    if isinstance(agent, dict) and isinstance(agent.get("pane_id"), str):
        return agent["pane_id"]
    raise ValueError(f"could not resolve '{target}' to a pane")


def _is_wait_timeout(error: client.HerdrError) -> bool:
    code = error.code.lower()
    return "timeout" in code or "timed_out" in code


async def chunked_wait(
    env: HerdrEnv,
    method: str,
    params: dict[str, object],
    *,
    timeout_ms: int | None,
    signal: object,
    not_found_grace_ms: int = 0,
) -> dict[str, object] | None:
    """Run a server-side wait in small chunks.

    Tau's cancellation token is poll-only, so one long server wait
    would make the tool uninterruptible; each chunk gives the server
    `timeout_ms <= WAIT_CHUNK_MS` and checks the token in between.
    A chunk's timeout error means "keep waiting". Returns the success
    payload, or `None` when the overall deadline passes.
    `timeout_ms=None` waits until cancelled.
    `not_found_grace_ms` tolerates a target that does not exist yet
    (a freshly spawned tau pane is invisible until its self-report
    lands).
    """
    started = time.monotonic()
    deadline = None if timeout_ms is None else started + timeout_ms / 1000
    grace_deadline = started + not_found_grace_ms / 1000
    while True:
        if cancelled(signal):
            raise ValueError("cancelled while waiting")
        now = time.monotonic()
        if deadline is not None and now >= deadline:
            return None
        chunk_ms = WAIT_CHUNK_MS
        if deadline is not None:
            chunk_ms = min(chunk_ms, max(1, int((deadline - now) * 1000)))
        try:
            return await client.request(
                env.socket_path,
                method,
                params | {"timeout_ms": chunk_ms},
                timeout=chunk_ms / 1000 + WAIT_SLACK,
            )
        except client.HerdrError as error:
            if _is_wait_timeout(error):
                continue
            code = error.code.lower()
            if ("not_found" in code or "no_such" in code) and (
                time.monotonic() < grace_deadline
            ):
                await asyncio.sleep(0.5)
                continue
            raise
