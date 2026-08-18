"""herdr_delegate: one-shot spawn -> prompt -> wait -> read."""

from __future__ import annotations

import asyncio
import time

from .. import client
from .._env import HerdrEnv
from ._base import (
    READ_TIMEOUT,
    TRIVIAL_TIMEOUT,
    cancelled,
    chunked_wait,
    json_result,
    require_str,
    tool,
)
from .agents import start_agent

_BOOT_BUDGET_MS = 90_000
_SETTLE_S = 1.5
_STALL_WINDOW_S = 5.0
_PROMPT_ATTEMPTS = 3
_SETTLED = ("idle", "done", "blocked")


async def _agent_info(env: HerdrEnv, target: str) -> dict[str, object]:
    payload = await client.request(
        env.socket_path, "agent.get", {"target": target}, timeout=TRIVIAL_TIMEOUT
    )
    agent = payload.get("agent")
    return agent if isinstance(agent, dict) else {}


async def _read_text(env: HerdrEnv, target: str, lines: int) -> str:
    payload = await client.request(
        env.socket_path,
        "agent.read",
        {"target": target, "source": "recent", "lines": lines, "format": "text"},
        timeout=READ_TIMEOUT,
    )
    read = payload.get("read") if isinstance(payload.get("read"), dict) else {}
    return str(read.get("text", ""))


async def _submit_prompt(env: HerdrEnv, target: str, text: str, signal) -> None:
    """Prompt, and verify the agent actually reacted.

    A submitted prompt can be lost while an agent's TUI is still
    settling. `state_change_seq` moves on any status transition, so an
    unchanged seq for the whole stall window means the prompt did not
    land; re-send, at most `_PROMPT_ATTEMPTS` times.
    """
    for _ in range(_PROMPT_ATTEMPTS):
        before = (await _agent_info(env, target)).get("state_change_seq")
        await client.request(
            env.socket_path,
            "agent.prompt",
            {"target": target, "text": text},
            timeout=TRIVIAL_TIMEOUT,
        )
        stall_deadline = time.monotonic() + _STALL_WINDOW_S
        while time.monotonic() < stall_deadline:
            if cancelled(signal):
                raise ValueError("cancelled while delegating")
            info = await _agent_info(env, target)
            if (
                info.get("agent_status") not in ("idle", "unknown")
                or info.get("state_change_seq") != before
            ):
                return
            await asyncio.sleep(0.5)
    raise ValueError(
        f"the prompt did not reach the agent after {_PROMPT_ATTEMPTS} attempts"
    )


def build_tools(env: HerdrEnv) -> list:
    async def _delegate(arguments, signal):
        kind = require_str(arguments, "kind").lower()
        prompt = require_str(arguments, "prompt")
        on_blocked = str(arguments.get("on_blocked") or "return")
        timeout_ms = int(arguments.get("timeout_ms") or 120_000)
        lines = int(arguments.get("lines") or 50)

        info = await start_agent(env, arguments, signal)
        pane_id = str(info["pane_id"])

        booted = await chunked_wait(
            env,
            "agent.wait",
            {"target": pane_id, "until": ["idle"]},
            timeout_ms=_BOOT_BUDGET_MS,
            signal=signal,
            # A spawned tau pane is invisible until its self-report lands.
            not_found_grace_ms=_BOOT_BUDGET_MS if kind == "tau" else 0,
        )
        if booted is None:
            raise ValueError(
                f"the {kind} agent in {pane_id} did not become ready within "
                f"{_BOOT_BUDGET_MS}ms (pane left open for inspection)"
            )
        await asyncio.sleep(_SETTLE_S)

        await _submit_prompt(env, pane_id, prompt, signal)

        done = await chunked_wait(
            env,
            "agent.wait",
            {"target": pane_id, "until": list(_SETTLED)},
            timeout_ms=timeout_ms,
            signal=signal,
        )
        if done is None:
            partial = await _read_text(env, pane_id, lines)
            raise ValueError(
                f"timed out after {timeout_ms}ms waiting for the {kind} agent "
                f"in {pane_id} (pane left open). Partial output:\n{partial}"
            )

        status = str((await _agent_info(env, pane_id)).get("agent_status", "unknown"))
        if status == "blocked" and on_blocked == "wait":
            while True:
                settled = await chunked_wait(
                    env,
                    "agent.wait",
                    {"target": pane_id, "until": ["idle", "done"]},
                    timeout_ms=None,
                    signal=signal,
                )
                status = str(
                    (settled or {}).get("agent", {}).get("agent_status", "unknown")
                )
                if status in ("idle", "done"):
                    break

        text = await _read_text(env, pane_id, lines)
        if status == "blocked":
            raise ValueError(
                f"the delegated agent in {pane_id} is blocked on a question:\n"
                f"{text}\n"
                "Relay the question to the user, answer with herdr_send_prompt, "
                "then herdr_wait_agent and herdr_read_agent."
            )

        if arguments.get("close_on_success"):
            await client.request(
                env.socket_path,
                "pane.close",
                {"pane_id": pane_id},
                timeout=TRIVIAL_TIMEOUT,
            )
        return json_result(
            {"pane_id": pane_id, "status": status, "output": text},
            text=text,
        )

    return [
        tool(
            "herdr_delegate",
            "Spawn an agent in a new herdr pane, send it one prompt, wait for "
            "it to finish, and return its output. On a blocked question the "
            "default is to error with the question so you can relay it "
            "(on_blocked=wait keeps waiting instead).",
            {
                "kind": {"type": "string", "description": "Agent kind, e.g. claude, tau."},
                "prompt": {"type": "string"},
                "name": {"type": "string"},
                "cwd": {"type": "string"},
                "args": {"type": "array", "items": {"type": "string"}},
                "env": {"type": "object", "additionalProperties": {"type": "string"}},
                "workspace_id": {"type": "string"},
                "direction": {"type": "string", "enum": ["right", "down"]},
                "on_blocked": {"type": "string", "enum": ["return", "wait"]},
                "close_on_success": {"type": "boolean"},
                "timeout_ms": {
                    "type": "integer",
                    "description": "Budget for the answer (default 120000).",
                },
                "lines": {"type": "integer", "description": "Lines to read back."},
            },
            _delegate,
            required=("kind", "prompt"),
        )
    ]
