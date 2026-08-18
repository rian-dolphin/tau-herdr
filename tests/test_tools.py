"""Tests for the v0.2 orchestration tool surface."""

import sys

import pytest

from test_extension import _load_runtime

pytestmark = pytest.mark.anyio

_TIMEOUT = {"__error__": {"code": "timeout", "message": "wait timed out"}}


def _tool(runtime, name):
    match = [t for t in runtime.extension_tools if t.name == name]
    assert match, f"tool {name} not registered"
    return match[0]


async def _run(runtime, name, arguments, signal=None):
    result = await _tool(runtime, name).execute("call-1", arguments, signal)
    text = "".join(c.text for c in result.content if hasattr(c, "text"))
    return text, result.details


class FakeSignal:
    def __init__(self, cancel_after: int) -> None:
        self.cancel_after = cancel_after
        self.checks = 0

    def is_cancelled(self) -> bool:
        self.checks += 1
        return self.checks > self.cancel_after


def _patch_delegate_speed(monkeypatch) -> None:
    """Shrink delegate sleeps in the runtime-loaded synthetic module."""
    for name, module in list(sys.modules.items()):
        if name.startswith("tau_extension_tau_herdr") and name.endswith(
            ".tools.delegate"
        ):
            monkeypatch.setattr(module, "_SETTLE_S", 0.01)
            monkeypatch.setattr(module, "_STALL_WINDOW_S", 0.3)


def _agent(status, seq=1, **extra):
    return {
        "type": "agent_info",
        "agent": {
            "pane_id": "w1:p9",
            "agent_status": status,
            "state_change_seq": seq,
            **extra,
        },
    }


async def test_tools_registered_only_inside_herdr(tmp_path, monkeypatch, fake_herdr):
    outside = _load_runtime(tmp_path, monkeypatch, socket_path=None)
    assert outside.extension_tools == ()
    monkeypatch.undo()
    inside = _load_runtime(tmp_path, monkeypatch, socket_path=fake_herdr.socket_path)
    names = {t.name for t in inside.extension_tools}
    assert "herdr_start_agent" in names
    assert "herdr_delegate" in names
    assert "herdr_layout" in names
    assert len(names) == 22
    assert inside.prompt_guidelines != ()
    assert inside.diagnostics == ()


async def test_start_agent_splits_then_starts(tmp_path, monkeypatch, fake_herdr):
    runtime = _load_runtime(tmp_path, monkeypatch, socket_path=fake_herdr.socket_path)
    fake_herdr.script["pane.split"] = [
        {"type": "pane_info", "pane": {"pane_id": "w1:p9", "tab_id": "w1:t1"}}
    ]
    fake_herdr.script["agent.start"] = [
        {"type": "agent_started", "agent": {"pane_id": "w1:p9", "agent_status": "idle"}}
    ]
    text, details = await _run(
        runtime, "herdr_start_agent", {"kind": "claude", "name": "helper", "cwd": "/x"}
    )
    assert "w1:p9" in text
    split = fake_herdr.requests_for("pane.split")[0]["params"]
    assert split["direction"] == "right" and split["cwd"] == "/x"
    start = fake_herdr.requests_for("agent.start")[0]["params"]
    assert start == {
        "name": "helper",
        "kind": "claude",
        "pane_id": "w1:p9",
        "timeout_ms": 30000,
    }


async def test_start_tau_agent_types_command(tmp_path, monkeypatch, fake_herdr):
    runtime = _load_runtime(tmp_path, monkeypatch, socket_path=fake_herdr.socket_path)
    fake_herdr.script["pane.split"] = [
        {"type": "pane_info", "pane": {"pane_id": "w1:p9"}}
    ]
    await _run(runtime, "herdr_start_agent", {"kind": "tau", "args": ["-e", "./x"]})
    assert fake_herdr.requests_for("agent.start") == []
    sent = fake_herdr.requests_for("pane.send_input")[0]["params"]
    assert sent == {"pane_id": "w1:p9", "text": "tau -e ./x", "keys": ["Enter"]}


async def test_start_agent_rejects_uppercase_name(tmp_path, monkeypatch, fake_herdr):
    runtime = _load_runtime(tmp_path, monkeypatch, socket_path=fake_herdr.socket_path)
    with pytest.raises(ValueError, match="lowercase"):
        await _run(runtime, "herdr_start_agent", {"kind": "claude", "name": "Helper"})


async def test_send_prompt_submit_and_type(tmp_path, monkeypatch, fake_herdr):
    runtime = _load_runtime(tmp_path, monkeypatch, socket_path=fake_herdr.socket_path)
    await _run(runtime, "herdr_send_prompt", {"target": "helper", "text": "hi"})
    assert fake_herdr.requests_for("agent.prompt")[0]["params"] == {
        "target": "helper",
        "text": "hi",
    }
    await _run(
        runtime,
        "herdr_send_prompt",
        {"target": "w1:p9", "text": "hi", "submit": False},
    )
    assert fake_herdr.requests_for("pane.send_text")[0]["params"] == {
        "pane_id": "w1:p9",
        "text": "hi",
    }


async def test_wait_agent_times_out_with_status(tmp_path, monkeypatch, fake_herdr):
    runtime = _load_runtime(tmp_path, monkeypatch, socket_path=fake_herdr.socket_path)
    fake_herdr.defaults["agent.wait"] = _TIMEOUT
    fake_herdr.defaults["agent.get"] = _agent("working")
    with pytest.raises(ValueError, match="working"):
        await _run(
            runtime, "herdr_wait_agent", {"target": "w1:p9", "timeout_ms": 300}
        )
    chunk = fake_herdr.requests_for("agent.wait")[0]["params"]
    assert chunk["timeout_ms"] <= 300


async def test_wait_agent_chunks_long_waits(tmp_path, monkeypatch, fake_herdr):
    runtime = _load_runtime(tmp_path, monkeypatch, socket_path=fake_herdr.socket_path)
    fake_herdr.script["agent.wait"] = [_TIMEOUT, _TIMEOUT, _agent("idle")]
    text, _ = await _run(
        runtime, "herdr_wait_agent", {"target": "w1:p9", "timeout_ms": 60_000}
    )
    assert "idle" in text
    waits = fake_herdr.requests_for("agent.wait")
    assert len(waits) == 3
    assert all(w["params"]["timeout_ms"] <= 2000 for w in waits)


async def test_wait_agent_polls_cancellation(tmp_path, monkeypatch, fake_herdr):
    runtime = _load_runtime(tmp_path, monkeypatch, socket_path=fake_herdr.socket_path)
    fake_herdr.defaults["agent.wait"] = _TIMEOUT
    with pytest.raises(ValueError, match="cancelled"):
        await _run(
            runtime,
            "herdr_wait_agent",
            {"target": "w1:p9", "timeout_ms": 60_000},
            signal=FakeSignal(cancel_after=2),
        )


async def test_read_agent_maps_source_spelling(tmp_path, monkeypatch, fake_herdr):
    runtime = _load_runtime(tmp_path, monkeypatch, socket_path=fake_herdr.socket_path)
    fake_herdr.script["agent.read"] = [
        {"type": "pane_read", "read": {"text": "hello"}}
    ]
    text, _ = await _run(
        runtime,
        "herdr_read_agent",
        {"target": "w1:p9", "source": "recent-unwrapped"},
    )
    assert text == "hello"
    read = fake_herdr.requests_for("agent.read")[0]["params"]
    assert read["source"] == "recent_unwrapped"


async def test_close_pane_resolves_agent_target(tmp_path, monkeypatch, fake_herdr):
    runtime = _load_runtime(tmp_path, monkeypatch, socket_path=fake_herdr.socket_path)
    fake_herdr.defaults["agent.get"] = _agent("idle")
    await _run(runtime, "herdr_close_pane", {"target": "helper"})
    assert fake_herdr.requests_for("pane.close")[0]["params"] == {"pane_id": "w1:p9"}
    await _run(runtime, "herdr_close_pane", {"target": "w2:p1"})
    assert fake_herdr.requests_for("pane.close")[1]["params"] == {"pane_id": "w2:p1"}


async def test_run_command_presses_enter(tmp_path, monkeypatch, fake_herdr):
    runtime = _load_runtime(tmp_path, monkeypatch, socket_path=fake_herdr.socket_path)
    await _run(
        runtime, "herdr_run_command", {"pane_id": "w1:p2", "command": "make test"}
    )
    assert fake_herdr.requests_for("pane.send_input")[0]["params"] == {
        "pane_id": "w1:p2",
        "text": "make test",
        "keys": ["Enter"],
    }


async def test_wait_output_needs_exactly_one_matcher(tmp_path, monkeypatch, fake_herdr):
    runtime = _load_runtime(tmp_path, monkeypatch, socket_path=fake_herdr.socket_path)
    with pytest.raises(ValueError, match="exactly one"):
        await _run(runtime, "herdr_wait_output", {"pane_id": "w1:p2"})
    with pytest.raises(ValueError, match="exactly one"):
        await _run(
            runtime,
            "herdr_wait_output",
            {"pane_id": "w1:p2", "match": "ok", "regex": "ok"},
        )
    fake_herdr.script["pane.wait_for_output"] = [
        {"type": "output_matched", "matched_line": "BUILD OK"}
    ]
    text, _ = await _run(
        runtime, "herdr_wait_output", {"pane_id": "w1:p2", "match": "BUILD"}
    )
    assert "BUILD OK" in text
    params = fake_herdr.requests_for("pane.wait_for_output")[0]["params"]
    assert params["match"] == {"type": "substring", "value": "BUILD"}


async def test_layout_dispatch_and_validation(tmp_path, monkeypatch, fake_herdr):
    runtime = _load_runtime(tmp_path, monkeypatch, socket_path=fake_herdr.socket_path)
    await _run(runtime, "herdr_layout", {"action": "create_tab", "label": "build"})
    assert fake_herdr.requests_for("tab.create")[0]["params"] == {
        "label": "build",
        "focus": False,
    }
    with pytest.raises(ValueError, match="tab_id"):
        await _run(runtime, "herdr_layout", {"action": "focus_tab"})
    with pytest.raises(ValueError, match="unknown action"):
        await _run(runtime, "herdr_layout", {"action": "resize_pane"})
    with pytest.raises(ValueError, match="destination"):
        await _run(runtime, "herdr_layout", {"action": "move_pane", "pane_id": "w1:p2"})


async def test_worktree_create_and_remove(tmp_path, monkeypatch, fake_herdr):
    runtime = _load_runtime(tmp_path, monkeypatch, socket_path=fake_herdr.socket_path)
    fake_herdr.script["worktree.create"] = [
        {
            "type": "worktree_created",
            "workspace": {"workspace_id": "w9"},
            "root_pane": {"pane_id": "w9:p1"},
        }
    ]
    _, details = await _run(
        runtime, "herdr_worktree_create", {"branch": "fix-1", "cwd": "/repo"}
    )
    assert details["workspace"]["workspace_id"] == "w9"
    with pytest.raises(ValueError, match="workspace_id"):
        await _run(runtime, "herdr_worktree_remove", {})


async def test_notify(tmp_path, monkeypatch, fake_herdr):
    runtime = _load_runtime(tmp_path, monkeypatch, socket_path=fake_herdr.socket_path)
    await _run(runtime, "herdr_notify", {"title": "Done", "sound": "done"})
    assert fake_herdr.requests_for("notification.show")[0]["params"] == {
        "title": "Done",
        "sound": "done",
    }


async def test_herdr_error_is_model_readable(tmp_path, monkeypatch, fake_herdr):
    runtime = _load_runtime(tmp_path, monkeypatch, socket_path=fake_herdr.socket_path)
    fake_herdr.script["agent.get"] = [
        {"__error__": {"code": "agent_not_found", "message": "no agent 'ghost'"}}
    ]
    tool = _tool(runtime, "herdr_get_agent")
    with pytest.raises(Exception, match="no agent 'ghost'"):
        await tool.execute("call-1", {"target": "ghost"}, None)


async def test_delegate_happy_path(tmp_path, monkeypatch, fake_herdr):
    runtime = _load_runtime(tmp_path, monkeypatch, socket_path=fake_herdr.socket_path)
    _patch_delegate_speed(monkeypatch)
    fake_herdr.script["pane.split"] = [
        {"type": "pane_info", "pane": {"pane_id": "w1:p9"}}
    ]
    fake_herdr.script["agent.start"] = [{"type": "agent_started", "agent": {}}]
    fake_herdr.script["agent.wait"] = [_agent("idle", 1), _agent("idle", 3)]
    fake_herdr.script["agent.get"] = [
        _agent("idle", 1),  # before prompting
        _agent("working", 2),  # stall poll: the prompt landed
        _agent("idle", 3),  # final status
    ]
    fake_herdr.script["agent.read"] = [{"type": "pane_read", "read": {"text": "42"}}]
    text, details = await _run(
        runtime,
        "herdr_delegate",
        {"kind": "claude", "prompt": "what is 6x7?", "close_on_success": True},
    )
    assert text == "42"
    assert details["status"] == "idle"
    assert fake_herdr.requests_for("agent.prompt")[0]["params"]["text"] == "what is 6x7?"
    assert fake_herdr.requests_for("pane.close") != []


async def test_delegate_reprompts_when_stalled(tmp_path, monkeypatch, fake_herdr):
    runtime = _load_runtime(tmp_path, monkeypatch, socket_path=fake_herdr.socket_path)
    _patch_delegate_speed(monkeypatch)
    fake_herdr.script["pane.split"] = [
        {"type": "pane_info", "pane": {"pane_id": "w1:p9"}}
    ]
    fake_herdr.script["agent.start"] = [{"type": "agent_started", "agent": {}}]
    fake_herdr.script["agent.wait"] = [_agent("idle", 1), _agent("idle", 3)]
    fake_herdr.script["agent.get"] = [
        _agent("idle", 1),  # attempt 1: before
        _agent("idle", 1),  # attempt 1: stall poll — nothing moved
        _agent("idle", 1),  # attempt 2: before
        _agent("working", 2),  # attempt 2: it landed
        _agent("idle", 3),  # final status
    ]
    fake_herdr.script["agent.read"] = [{"type": "pane_read", "read": {"text": "ok"}}]
    text, _ = await _run(runtime, "herdr_delegate", {"kind": "claude", "prompt": "go"})
    assert text == "ok"
    assert len(fake_herdr.requests_for("agent.prompt")) == 2


async def test_delegate_blocked_returns_question(tmp_path, monkeypatch, fake_herdr):
    runtime = _load_runtime(tmp_path, monkeypatch, socket_path=fake_herdr.socket_path)
    _patch_delegate_speed(monkeypatch)
    fake_herdr.script["pane.split"] = [
        {"type": "pane_info", "pane": {"pane_id": "w1:p9"}}
    ]
    fake_herdr.script["agent.start"] = [{"type": "agent_started", "agent": {}}]
    fake_herdr.script["agent.wait"] = [_agent("idle", 1), _agent("blocked", 3)]
    fake_herdr.script["agent.get"] = [
        _agent("idle", 1),
        _agent("working", 2),
        _agent("blocked", 3),
    ]
    fake_herdr.script["agent.read"] = [
        {"type": "pane_read", "read": {"text": "Which database should I use?"}}
    ]
    with pytest.raises(ValueError, match="Which database"):
        await _run(runtime, "herdr_delegate", {"kind": "claude", "prompt": "go"})
    # The pane stays open so the orchestrator can answer.
    assert fake_herdr.requests_for("pane.close") == []
