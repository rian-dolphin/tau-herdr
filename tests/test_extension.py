"""Tests for the tau-herdr extension.

Requires Tau's packages on the import path: either
`uv run pytest` (tau-ai from PyPI via the dev group) or a local Tau
checkout's env: `uv run --project /path/to/tau pytest tests/`.
"""

import time
from pathlib import Path

import pytest

from tau_agent.events import AgentStartEvent
from tau_coding import TauResourcePaths
from tau_coding.events import AgentSettledEvent
from tau_coding.extensions import ExtensionRuntime

pytestmark = pytest.mark.anyio

REPO_ROOT = Path(__file__).resolve().parent.parent

def _paths(tmp_path: Path) -> TauResourcePaths:
    return TauResourcePaths(
        root=tmp_path / "home-tau",
        cwd=tmp_path / "project",
        agents_root=tmp_path / "home-agents",
    )


class RecordingSession:
    """Minimal BoundSession implementation for runtime tests."""

    def __init__(self, tmp_path: Path, *, session_id: str | None = "session-1") -> None:
        self.cwd = tmp_path
        self.model = "fake"
        self.provider_name = "fake"
        self.inference_provider = None
        self.session_id = session_id
        self.system_prompt = "You are Tau."
        self.is_running = False
        self.messages: list[object] = []

    def queue_steering_message(self, content, *, custom_type=None, details=None):
        pass

    def queue_follow_up_message(self, content, *, custom_type=None, details=None):
        pass

    async def append_custom_entry(self, namespace, data):
        pass


def _load_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    socket_path: str | None,
    session_id: str | None = "session-1",
    extra_env: dict[str, str] | None = None,
) -> ExtensionRuntime:
    if socket_path is not None:
        monkeypatch.setenv("HERDR_ENV", "1")
        monkeypatch.setenv("HERDR_PANE_ID", "w1:p1")
        monkeypatch.setenv("HERDR_SOCKET_PATH", socket_path)
    for name, value in (extra_env or {}).items():
        monkeypatch.setenv(name, value)
    runtime = ExtensionRuntime()
    runtime.load(
        _paths(tmp_path),
        extra_paths=(REPO_ROOT,),
        include_resource_dirs=False,
    )
    runtime.bind(RecordingSession(tmp_path, session_id=session_id))
    return runtime


async def test_dormant_outside_herdr(tmp_path, monkeypatch):
    runtime = _load_runtime(tmp_path, monkeypatch, socket_path=None)
    assert runtime.extension_names == ("tau_herdr",)
    assert runtime.diagnostics == ()
    registry = runtime.build_command_registry()
    assert registry.get("herdr") is None
    await runtime.emit_session_start("startup")
    await runtime.emit_session_shutdown("quit")
    assert runtime.diagnostics == ()


async def test_dormant_when_disabled(tmp_path, monkeypatch, fake_herdr):
    runtime = _load_runtime(
        tmp_path,
        monkeypatch,
        socket_path=fake_herdr.socket_path,
        extra_env={"TAU_HERDR_DISABLE": "1"},
    )
    assert runtime.diagnostics == ()
    await runtime.emit_session_start("startup")
    await runtime.emit_session_shutdown("quit")
    assert fake_herdr.requests == []


async def test_reports_state_sequence(tmp_path, monkeypatch, fake_herdr):
    runtime = _load_runtime(tmp_path, monkeypatch, socket_path=fake_herdr.socket_path)
    await runtime.emit_session_start("startup")
    await runtime.emit_event(AgentStartEvent())
    await runtime.emit_event(AgentSettledEvent())
    await runtime.emit_session_shutdown("quit")
    assert runtime.diagnostics == ()

    reports = fake_herdr.requests_for("pane.report_agent")
    assert [r["params"]["state"] for r in reports] == ["idle", "working", "idle"]
    for report in reports:
        assert report["params"]["pane_id"] == "w1:p1"
        assert report["params"]["source"] == "tau-herdr"
        assert report["params"]["agent"] == "tau"
    seqs = [r["params"]["seq"] for r in reports]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)

    sessions = fake_herdr.requests_for("pane.report_agent_session")
    assert len(sessions) == 1
    assert sessions[0]["params"]["agent_session_id"] == "session-1"
    assert sessions[0]["params"]["session_start_source"] == "startup"

    releases = fake_herdr.requests_for("pane.release_agent")
    assert len(releases) == 1
    assert releases[0]["params"]["agent"] == "tau"
    # The release must land after every queued report.
    assert fake_herdr.requests[-1]["method"] == "pane.release_agent"


async def test_no_release_without_quit(tmp_path, monkeypatch, fake_herdr):
    runtime = _load_runtime(tmp_path, monkeypatch, socket_path=fake_herdr.socket_path)
    await runtime.emit_session_start("startup")
    await runtime.emit_session_shutdown("reload")
    assert runtime.diagnostics == ()
    assert fake_herdr.requests_for("pane.release_agent") == []
    assert fake_herdr.requests_for("pane.report_agent") != []


async def test_skips_session_report_without_session_id(
    tmp_path, monkeypatch, fake_herdr
):
    runtime = _load_runtime(
        tmp_path, monkeypatch, socket_path=fake_herdr.socket_path, session_id=None
    )
    await runtime.emit_session_start("startup")
    await runtime.emit_session_shutdown("quit")
    assert runtime.diagnostics == ()
    assert fake_herdr.requests_for("pane.report_agent_session") == []
    assert fake_herdr.requests_for("pane.report_agent") != []


async def test_label_overrides(tmp_path, monkeypatch, fake_herdr):
    runtime = _load_runtime(
        tmp_path,
        monkeypatch,
        socket_path=fake_herdr.socket_path,
        extra_env={
            "HERDR_AGENT_LABEL": "herdr-says",
            "TAU_HERDR_AGENT_LABEL": "tau-says",
        },
    )
    await runtime.emit_session_start("startup")
    await runtime.emit_session_shutdown("quit")
    labels = {r["params"]["agent"] for r in fake_herdr.requests}
    assert labels == {"tau-says"}


async def test_socket_down_is_silent(tmp_path, monkeypatch):
    runtime = _load_runtime(
        tmp_path, monkeypatch, socket_path=str(tmp_path / "missing.sock")
    )
    assert runtime.build_command_registry().get("herdr") is not None
    await runtime.emit_session_start("startup")
    await runtime.emit_event(AgentStartEvent())
    await runtime.emit_session_shutdown("quit")
    assert runtime.diagnostics == ()


async def test_handlers_do_not_block_on_socket(tmp_path, monkeypatch, fake_herdr):
    # The central transport claim: handlers only enqueue. A server that
    # accepts but never replies must not stall event dispatch.
    fake_herdr.hang = True
    runtime = _load_runtime(tmp_path, monkeypatch, socket_path=fake_herdr.socket_path)
    started = time.perf_counter()
    await runtime.emit_session_start("startup")
    await runtime.emit_event(AgentStartEvent())
    await runtime.emit_event(AgentSettledEvent())
    elapsed = time.perf_counter() - started
    assert elapsed < 0.3
    await runtime.emit_session_shutdown("quit")
    assert runtime.diagnostics == ()


async def test_reports_resume_after_reload(tmp_path, monkeypatch, fake_herdr):
    runtime = _load_runtime(tmp_path, monkeypatch, socket_path=fake_herdr.socket_path)
    await runtime.emit_session_start("startup")
    await runtime.emit_session_shutdown("reload")
    before = len(fake_herdr.requests_for("pane.report_agent"))

    await runtime.emit_session_start("reload")
    await runtime.emit_event(AgentStartEvent())
    await runtime.emit_session_shutdown("quit")
    assert runtime.diagnostics == ()
    after = fake_herdr.requests_for("pane.report_agent")
    assert [r["params"]["state"] for r in after[before:]] == ["idle", "working"]


def test_next_seq_strictly_increases(monkeypatch):
    from tau_herdr import extension as ext
    from tau_herdr._env import HerdrEnv

    monkeypatch.setattr(ext.time, "time_ns", lambda: 12345)
    reporter = ext._Reporter(HerdrEnv(pane_id="p", socket_path="s", label="tau"))
    assert [reporter._next_seq() for _ in range(3)] == [12345, 12346, 12347]


async def test_herdr_command_reports_status(tmp_path, monkeypatch, fake_herdr):
    runtime = _load_runtime(tmp_path, monkeypatch, socket_path=fake_herdr.socket_path)
    await runtime.emit_session_start("startup")
    await runtime.emit_event(AgentStartEvent())
    await runtime.emit_session_shutdown("reload")

    registry = runtime.build_command_registry()
    command = registry.get("herdr")
    assert command is not None
    text = _run_command(registry, command)
    assert "w1:p1" in text
    assert "working" in text
    assert "ok" in text
    assert runtime.diagnostics == ()


async def test_herdr_command_shows_failure(tmp_path, monkeypatch):
    runtime = _load_runtime(
        tmp_path, monkeypatch, socket_path=str(tmp_path / "missing.sock")
    )
    await runtime.emit_session_start("startup")
    await runtime.emit_session_shutdown("reload")

    registry = runtime.build_command_registry()
    command = registry.get("herdr")
    text = _run_command(registry, command)
    assert "failed" in text
    assert runtime.diagnostics == ()


def _run_command(registry, command) -> str:
    from tau_coding.commands import CommandContext

    context = CommandContext(
        session=None, registry=registry, text="/herdr", name="herdr", args=""
    )
    result = command.handler(context)
    return result.message
