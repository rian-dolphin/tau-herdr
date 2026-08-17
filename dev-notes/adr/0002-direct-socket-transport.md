---
title: "ADR 0002 — Talk to the herdr socket directly, not the CLI"
---

## Status

Accepted

## Context

pi-herdr spawns the `herdr` CLI binary for every call and parses a JSON
envelope from stdout.
herdr's own reference integrations (for example the Claude hook) write
newline-delimited JSON straight to the Unix socket at
`HERDR_SOCKET_PATH` with a 0.5 s timeout.

Tau dispatches extension event handlers sequentially and without a
timeout.
`agent_start` is on the hot path of every run.
A blocking subprocess call there stalls the agent loop.
Even a non-blocking spawn costs tens of milliseconds and adds a PATH
dependency.

v0.1 uses only four socket methods with fixed shapes:
`pane.report_agent`, `pane.report_agent_session`, `pane.release_agent`,
and nothing else.

## Decision

We connect to `HERDR_SOCKET_PATH` with `asyncio.open_unix_connection`
and send one JSON line per call.
Each call has a 0.5 s timeout and swallows every exception.
We do not spawn the `herdr` binary.

## Consequences

- No subprocess on the hot path.
  Handlers only enqueue; a single worker task sends reports FIFO in the
  background, so a dead or slow herdr server costs the run nothing and
  never raises into Tau.
  The only awaited path is the queue drain at `session_shutdown`,
  bounded at 1 s plus 0.5 s for the release call on `quit`.
- The client is about 40 lines instead of pi-herdr's 215-line CLI
  wrapper.
- We depend on the socket protocol instead of the CLI surface.
  The four methods we use are the same ones herdr's own integrations
  use, so they are stable.
- A future v0.2 tool surface can revisit the CLI for version-tolerant
  orchestration calls.
  This record covers self-report only.
