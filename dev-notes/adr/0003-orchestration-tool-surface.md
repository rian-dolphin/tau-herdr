---
title: "ADR 0003 — v0.2 orchestration tools: socket transport, 22 tools, multiplexed layout"
---

## Status

Accepted
(Supersedes the deferral in ADR 0001; the self-report scope decision
there still stands.)

## Context

v0.1 shipped self-report only and deferred pi-herdr's 43 LLM-facing
tools.
The project owner wants the full orchestration surface.
pi-herdr spawns the `herdr` CLI for every tool call and branches on
herdr versions back to 0.7.x, with Windows-specific fallbacks.
We verified herdr 0.8.0's socket API (protocol 19) live: it covers
every capability we need except `pane run` (socket equivalent:
`pane.send_input` with `keys: ["Enter"]`) and session
list/stop/delete (no socket method).
Tau tool definitions cost system-prompt tokens on every turn.

## Decision

- Tools use the same Unix socket as self-report, through a new
  `request()` client entry point that raises `HerdrError` with
  model-readable messages.
  We do not spawn the `herdr` binary and we do not version-probe; we
  pin protocol 19.
- We register 22 tools, not 43.
  Core orchestration, pane sync, and worktree tools stay individual
  and keep pi-herdr's names.
  The 13 trivial layout passthroughs collapse into one `herdr_layout`
  tool with an `action` enum.
  Cut entirely: `herdr_explain_agent`, session tools, pane geometry
  (resize/zoom/swap), and all legacy-version branches.
- Long waits are chunked at 2 s per server call so Tau's poll-only
  cancellation token stays responsive.
- `herdr_delegate` defaults to `on_blocked: "return"` (pi-herdr
  defaults to an unbounded wait).

## Consequences

- One transport, one client module, no subprocess management, no
  version matrix.
  If a future herdr protocol breaks compatibility, we update once.
- The prompt cost is roughly half of a full pi-herdr port while every
  genuinely useful capability stays reachable.
  Layout actions are one hop less discoverable behind the enum; the
  tool description lists them all.
- Starting a *tau* pane uses split + typed command instead of
  `agent.start`, because herdr has no `tau` kind.
  The spawned Tau becomes visible through its own v0.1 self-report.
- Delegation never hangs by default; an orchestrator that wants
  pi-herdr's patient behavior passes `on_blocked: "wait"`.
