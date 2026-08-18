"""Tests for pane badges (ADR 0004)."""

import pytest

from tau_agent.messages import AssistantMessage, Usage, UsageCost
from tau_coding.extensions import TurnEndEvent

from tau_herdr.badges import BadgeTracker, compact_count, title_from_prompt
from test_extension import _load_runtime

pytestmark = pytest.mark.anyio


def test_title_from_prompt():
    assert title_from_prompt("Fix the build\nplease") == "Fix the build"
    assert title_from_prompt("   \n\n") is None
    long = "x" * 100
    title = title_from_prompt(long)
    assert len(title) == 60 and title.endswith("…")


def test_compact_count():
    assert compact_count(999) == "999"
    assert compact_count(48_200) == "48.2k"
    assert compact_count(48_000) == "48k"
    assert compact_count(1_500_000) == "1.5M"
    assert compact_count(999_999) == "1M"


def test_tracker_accumulates_cost_and_reports_context():
    tracker = BadgeTracker()
    usage = Usage(input=30_000, cache_read=10_000, cost=UsageCost(total=0.0))
    assert tracker.turn_tokens(usage) == {"ctx": "40k", "cost": None}
    usage = Usage(input=50_000, cost=UsageCost(total=0.05))
    assert tracker.turn_tokens(usage) == {"ctx": "50k", "cost": "$0.05"}
    usage = Usage(input=60_000, cost=UsageCost(total=0.05))
    assert tracker.turn_tokens(usage) == {"ctx": "60k", "cost": "$0.10"}
    tracker.reset()
    assert tracker.cost_total == 0.0


def _turn_end(usage: Usage, *, stop_reason: str = "stop") -> TurnEndEvent:
    # The extension-facing enriched event shape the runtime dispatches.
    return TurnEndEvent(
        turn_index=0,
        message=AssistantMessage(
            model="fake", content=[], usage=usage, stop_reason=stop_reason
        ),
        tool_results=[],
    )


async def test_badges_reported_over_the_wire(tmp_path, monkeypatch, fake_herdr):
    runtime = _load_runtime(tmp_path, monkeypatch, socket_path=fake_herdr.socket_path)
    await runtime.emit_session_start("startup")
    await runtime.run_input_hooks("Fix the flaky test\nwith details")
    await runtime.emit_event(
        _turn_end(Usage(input=30_000, cache_read=10_000, cost=UsageCost(total=0.25)))
    )
    await runtime.emit_session_shutdown("quit")
    assert runtime.diagnostics == ()

    reports = fake_herdr.requests_for("pane.report_metadata")
    start = reports[0]["params"]
    assert start["clear_title"] is True
    assert start["tokens"] == {"model": "fake", "ctx": None, "cost": None}
    title = reports[1]["params"]
    assert title["title"] == "Fix the flaky test"
    turn = reports[2]["params"]
    assert turn["tokens"] == {"ctx": "40k", "cost": "$0.25", "model": "fake"}
    seqs = [r["params"]["seq"] for r in reports]
    assert seqs == sorted(seqs)


async def test_aborted_turn_does_not_wipe_ctx(tmp_path, monkeypatch, fake_herdr):
    runtime = _load_runtime(tmp_path, monkeypatch, socket_path=fake_herdr.socket_path)
    await runtime.emit_session_start("startup")
    await runtime.emit_event(_turn_end(Usage(input=40_000)))
    # Esc / provider errors end the turn with a zeroed Usage.
    await runtime.emit_event(_turn_end(Usage(), stop_reason="aborted"))
    await runtime.emit_event(_turn_end(Usage(), stop_reason="error"))
    await runtime.emit_session_shutdown("quit")
    assert runtime.diagnostics == ()
    ctx_values = [
        r["params"]["tokens"]["ctx"]
        for r in fake_herdr.requests_for("pane.report_metadata")
        if r["params"].get("tokens", {}).get("ctx")
    ]
    assert ctx_values == ["40k"]


def test_ctx_prefers_provider_total_tokens():
    tracker = BadgeTracker()
    usage = Usage(input=0, total_tokens=52_000)
    assert tracker.turn_tokens(usage)["ctx"] == "52k"


async def test_extension_input_does_not_set_title(tmp_path, monkeypatch, fake_herdr):
    runtime = _load_runtime(tmp_path, monkeypatch, socket_path=fake_herdr.socket_path)
    await runtime.run_input_hooks("internal turn", source="extension")
    await runtime.emit_session_shutdown("reload")
    assert runtime.diagnostics == ()
    titles = [
        r
        for r in fake_herdr.requests_for("pane.report_metadata")
        if "title" in r["params"]
    ]
    assert titles == []


async def test_cost_resets_on_session_rebind(tmp_path, monkeypatch, fake_herdr):
    runtime = _load_runtime(tmp_path, monkeypatch, socket_path=fake_herdr.socket_path)
    await runtime.emit_session_start("startup")
    await runtime.emit_event(_turn_end(Usage(input=1000, cost=UsageCost(total=0.40))))
    await runtime.emit_session_start("new")
    await runtime.emit_event(_turn_end(Usage(input=1000, cost=UsageCost(total=0.10))))
    await runtime.emit_session_shutdown("quit")
    assert runtime.diagnostics == ()

    costs = [
        r["params"]["tokens"]["cost"]
        for r in fake_herdr.requests_for("pane.report_metadata")
        if r["params"].get("tokens", {}).get("cost") is not None
    ]
    assert costs == ["$0.40", "$0.10"]
