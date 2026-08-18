---
title: "ADR 0006 — Remove the native tool surface"
---

## Status

Accepted
(Supersedes the tool surface in ADR 0003 and the `TAU_HERDR_TOOLS`
opt-in in ADR 0005.)

## Context

ADR 0005 made the 22-tool surface opt-in and shipped orchestration as
the `herdr` skill.
That left two parallel orchestration paths.
Every herdr behavior we discover (the `agent_not_ready` typed-prompt
fallback, the missing `tau` kind, wait semantics) had to be encoded
twice: once in `SKILL.md`, once in the tools code.
The opt-in path would get almost no real-world exercise, and it pins
socket protocol 19, so a herdr protocol bump would break it silently
for whoever enabled it.
The tools package and its tests were about half of the repository.

## Decision

Delete the tool surface: `src/tau_herdr/tools/`, `tests/test_tools.py`,
and the now-dead `client.request()` / `HerdrError` and
`TAU_HERDR_TOOLS` gate.
The `herdr` skill is the only orchestration path.
The last release with the tools is tagged `v0.4.0`; resurrect from
history if structured tools ever earn their maintenance cost.

## Consequences

- One orchestration path to keep correct, and it is the
  version-tolerant one (herdr maintains CLI compatibility; the socket
  protocol is an internal contract).
- The extension is back to its v0.1 size: self-report, badges,
  `/herdr`, one skill file.
- Lost until resurrected: cancellation-responsive chunked waits and
  `herdr_delegate`'s retry state machine.
  A CLI `herdr agent wait` blocks the shell tool for its timeout; the
  skill mitigates by recommending bounded timeouts.
