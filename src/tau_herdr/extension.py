"""Report Tau's agent state to the herdr workspace manager.

herdr cannot detect Tau natively; this extension makes a Tau pane show
up in `herdr agent list` with live working/idle state. See
`dev-notes/spec.md` for the design.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import TYPE_CHECKING

from . import client
from ._env import HerdrEnv

if TYPE_CHECKING:
    from tau_coding.extensions import (
        ExtensionAPI,
        ExtensionCommandContext,
        ExtensionContext,
    )

SOURCE = "tau-herdr"
DRAIN_TIMEOUT = 1.0


class _Reporter:
    """Owns the report queue and the single worker task.

    Event handlers only enqueue (Tau awaits handlers inline on the
    run's critical path); the worker sends requests FIFO. The worker
    holds nothing from the extension API, so a stale generation after
    `/reload` cannot bite — the old runtime's `session_shutdown` stops
    the worker.
    """

    def __init__(self, env: HerdrEnv) -> None:
        self._env = env
        self._queue: asyncio.Queue[tuple[str, dict[str, object]]] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._last_seq = 0
        self.last_state: str | None = None
        self.last_ok: bool | None = None

    def _next_seq(self) -> int:
        # Clock-seeded so restarts are never stale; incremented so
        # ordering stays strict within one clock tick.
        self._last_seq = max(self._last_seq + 1, time.time_ns())
        return self._last_seq

    def _base_params(self) -> dict[str, object]:
        return {
            "pane_id": self._env.pane_id,
            "source": SOURCE,
            "agent": self._env.label,
            "seq": self._next_seq(),
        }

    def report_state(self, state: str) -> None:
        self.last_state = state
        self._enqueue("pane.report_agent", self._base_params() | {"state": state})

    def report_session(self, session_id: str, *, reason: str) -> None:
        params = self._base_params() | {
            "agent_session_id": session_id,
            "session_start_source": reason,
        }
        self._enqueue("pane.report_agent_session", params)

    def _enqueue(self, method: str, params: dict[str, object]) -> None:
        self._queue.put_nowait((method, params))
        if self._worker is None or self._worker.done():
            self._worker = asyncio.get_running_loop().create_task(self._run())

    async def _run(self) -> None:
        while True:
            method, params = await self._queue.get()
            try:
                response = await client.call(self._env.socket_path, method, params)
                self.last_ok = response is not None and "error" not in response
            finally:
                self._queue.task_done()

    async def shutdown(self, *, release: bool) -> None:
        """Drain pending reports, optionally release the pane, stop.

        Called on every `session_shutdown`: the process exits right
        after `quit`, and after `reload`/`new`/`resume`/`branch` a new
        runtime (and reporter) takes over.
        """
        try:
            await asyncio.wait_for(self._queue.join(), DRAIN_TIMEOUT)
        except (TimeoutError, asyncio.TimeoutError):
            pass
        if self._worker is not None:
            self._worker.cancel()
            self._worker = None
        if release:
            params = {
                "pane_id": self._env.pane_id,
                "source": SOURCE,
                "agent": self._env.label,
            }
            response = await client.call(
                self._env.socket_path, "pane.release_agent", params
            )
            self.last_ok = response is not None and "error" not in response

    def status_text(self) -> str:
        if self.last_ok is None:
            last_report = "none sent yet"
        elif self.last_ok:
            last_report = "ok"
        else:
            last_report = "failed (is the herdr server running?)"
        return "\n".join(
            [
                "herdr integration",
                f"  pane:       {self._env.pane_id}",
                f"  socket:     {self._env.socket_path}",
                f"  label:      {self._env.label}",
                f"  last state: {self.last_state or 'none reported yet'}",
                f"  last report: {last_report}",
            ]
        )


def setup(tau: "ExtensionAPI") -> None:
    """Subscribe the reporter when running inside a herdr pane."""
    env = HerdrEnv.from_environ(os.environ)
    if env is None:
        return
    reporter = _Reporter(env)

    @tau.on("session_start")
    async def _on_session_start(event, context: "ExtensionContext") -> None:
        reporter.report_state("idle")
        session_id = context.session_id
        if session_id:
            reporter.report_session(session_id, reason=event.reason)

    @tau.on("agent_start")
    async def _on_agent_start(event, context: "ExtensionContext") -> None:
        del event, context
        reporter.report_state("working")

    @tau.on("agent_settled")
    async def _on_agent_settled(event, context: "ExtensionContext") -> None:
        del event, context
        reporter.report_state("idle")

    @tau.on("session_shutdown")
    async def _on_session_shutdown(event, context: "ExtensionContext") -> None:
        del context
        await reporter.shutdown(release=event.reason == "quit")

    def _herdr_command(args: str, context: "ExtensionCommandContext") -> str:
        del args, context
        return reporter.status_text()

    tau.register_command(
        "herdr",
        _herdr_command,
        description="Show herdr integration status.",
    )
