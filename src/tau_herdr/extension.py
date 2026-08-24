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
from .badges import BadgeTracker
from ._env import HerdrEnv

if TYPE_CHECKING:
    from tau_coding.extensions import (
        ExtensionAPI,
        ExtensionCommandContext,
        ExtensionContext,
    )

SOURCE = "tau-herdr"
DRAIN_TIMEOUT = 1.0
OWNER_PID_ENV = "TAU_HERDR_OWNER_PID"
IDLE_REPORT_DELAY = 2.0
ERROR_IDLE_REPORT_DELAY = 5.0


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
        self._pending_idle: asyncio.Task[None] | None = None
        self._last_seq = 0
        self.last_state: str | None = None
        self.last_outcome: str | None = None
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
        self._enqueue("pane.report_agent", self._base_params() | {"state": state})

    def report_working(self) -> None:
        self.cancel_pending_idle()
        self.report_state("working")

    def schedule_idle(self, *, outcome: str) -> None:
        """Report idle only if another run does not begin shortly.

        Herdr turns a background working-to-idle transition into a done
        notification. Tau can settle a failed run and immediately start a
        separate continuation, so reporting synchronously creates false
        "finished" notifications that cannot be retracted.
        """
        self.cancel_pending_idle()
        self.last_outcome = outcome
        delay = (
            ERROR_IDLE_REPORT_DELAY
            if outcome in {"error", "aborted"}
            else IDLE_REPORT_DELAY
        )
        self._pending_idle = asyncio.get_running_loop().create_task(
            self._report_idle_after(delay)
        )

    async def _report_idle_after(self, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            self.report_state("idle")
        except asyncio.CancelledError:
            raise
        finally:
            if self._pending_idle is asyncio.current_task():
                self._pending_idle = None

    def cancel_pending_idle(self) -> None:
        if self._pending_idle is not None:
            self._pending_idle.cancel()
            self._pending_idle = None

    def report_session(self, session_id: str, *, reason: str) -> None:
        params = self._base_params() | {
            "agent_session_id": session_id,
            "session_start_source": reason,
        }
        self._enqueue("pane.report_agent_session", params)

    def report_metadata(self, fields: dict[str, object]) -> None:
        self._enqueue("pane.report_metadata", self._base_params() | fields)

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
                if method == "pane.report_agent":
                    self.last_state = str(params.get("state"))
            except Exception:
                # A dead worker would silence all future reports and log
                # an unretrieved exception into the host's stderr.
                self.last_ok = False
            finally:
                self._queue.task_done()

    async def shutdown(self, *, release: bool) -> None:
        """Drain pending reports, optionally release the pane, stop.

        Called on every `session_shutdown`: the process exits right
        after `quit`, and after `reload`/`new`/`resume`/`branch` a new
        runtime (and reporter) takes over.
        """
        self.cancel_pending_idle()
        try:
            await asyncio.wait_for(self._queue.join(), DRAIN_TIMEOUT)
        except (TimeoutError, asyncio.TimeoutError):
            pass
        if self._worker is not None:
            worker, self._worker = self._worker, None
            worker.cancel()
            # Await the cancellation: on `quit` the loop closes moments
            # later and an un-awaited task logs "Task was destroyed".
            await asyncio.gather(worker, return_exceptions=True)
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
                f"  last outcome: {self.last_outcome or 'none observed yet'}",
                f"  idle pending: {'yes' if self._pending_idle is not None else 'no'}",
                f"  last report: {last_report}",
            ]
        )


def setup(tau: "ExtensionAPI") -> None:
    """Subscribe the reporter when running inside a herdr pane."""
    env = HerdrEnv.from_environ(os.environ)
    if env is None:
        return

    # Tool subprocesses inherit the pane's HERDR_* environment. Without an
    # ownership marker, a nested Tau process (notably Tau's own test suite)
    # can report its temporary sessions against the parent pane and produce
    # false idle notifications or release the parent's agent authority.
    # Environment changes stay scoped to this process and its descendants,
    # so a later Tau launched by the pane's shell can claim ownership anew.
    current_pid = str(os.getpid())
    owner_pid = os.environ.get(OWNER_PID_ENV)
    if owner_pid is not None and owner_pid != current_pid:
        return
    os.environ[OWNER_PID_ENV] = current_pid

    reporter = _Reporter(env)

    # The extension is invisible to the model: no tools, no prompt
    # guideline. Orchestration lives in the `herdr` skill
    # (/skill:herdr) — see ADR 0005 and ADR 0006.

    tracker = BadgeTracker()
    run_outcome = "success"

    @tau.on("session_start")
    async def _on_session_start(event, context: "ExtensionContext") -> None:
        reporter.report_state("idle")
        session_id = context.session_id
        if session_id:
            reporter.report_session(session_id, reason=event.reason)
        tracker.reset()
        reporter.report_metadata(
            {"tokens": {"model": context.model, "ctx": None, "cost": None}}
        )

    @tau.on("turn_end")
    async def _on_turn_end(event, context: "ExtensionContext") -> None:
        message = getattr(event, "message", None)
        usage = getattr(message, "usage", None)
        if usage is None:
            return
        # Interrupted and errored turns carry a zeroed Usage; reporting
        # it would wipe the real context badge (tau's own meter skips
        # these messages too).
        if getattr(message, "stop_reason", "stop") in ("error", "aborted"):
            return
        tokens = tracker.turn_tokens(usage)
        tokens["model"] = context.model
        reporter.report_metadata({"tokens": tokens})

    @tau.on("agent_start")
    async def _on_agent_start(_event, _context: "ExtensionContext") -> None:
        nonlocal run_outcome
        run_outcome = "success"
        reporter.report_working()

    @tau.on("message_end")
    async def _on_message_end(event, _context: "ExtensionContext") -> None:
        nonlocal run_outcome
        message = getattr(event, "message", None)
        stop_reason = getattr(message, "stop_reason", None)
        if stop_reason in {"error", "aborted"}:
            run_outcome = stop_reason

    @tau.on("agent_settled")
    async def _on_agent_settled(_event, _context: "ExtensionContext") -> None:
        reporter.schedule_idle(outcome=run_outcome)

    @tau.on("session_shutdown")
    async def _on_session_shutdown(event, _context: "ExtensionContext") -> None:
        await reporter.shutdown(release=event.reason == "quit")

    def _herdr_command(_args: str, _context: "ExtensionCommandContext") -> str:
        return reporter.status_text()

    tau.register_command(
        "herdr",
        _herdr_command,
        description="Show herdr integration status.",
    )
