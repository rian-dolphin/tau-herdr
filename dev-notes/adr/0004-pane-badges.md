---
title: "ADR 0004 — Pane badges: title from the prompt, model/ctx/cost tokens"
---

## Status

Accepted

## Context

herdr shows display-only pane metadata reported through
`pane.report_metadata`: a pane `title`, up to 16 named string
`tokens`, per-status `state_labels`, and a `display_agent`.
herdr-managed agents (claude, codex) get useful titles because their
CLIs set the terminal title themselves.
A tau pane shows only "τ", and no usage information.

Tau's extension API exposes the user's prompt (the `input` hook), the
model (`context.model`), and per-turn `Usage` with token counts and
USD cost (`turn_end`).

## Decision

Report three things, through the existing self-report queue (shared
`seq`, shared shutdown drain):

- `title`: the first line of the latest user prompt, truncated to 60
  characters.
  Reported on the `input` hook; cleared on every `session_start` so a
  resumed or new session does not keep a stale title.
- Token `model`: from `context.model`, refreshed on `session_start`
  and every `turn_end` (the model can change mid-session via
  `/model`; there is no dedicated change event).
- Tokens `ctx` and `cost`: on `turn_end`, `ctx` is the last assistant
  message's context size (`input + cache_read + cache_write`,
  compact-formatted, e.g. `48.2k`), and `cost` is the session's
  accumulated `usage.cost.total` (`$0.42`), omitted while zero
  because many providers report no cost.
  The accumulator resets on `session_start`.

We do not set `state_labels` or `display_agent` (herdr's defaults are
fine), and we set no `ttl_ms` (badges die with the pane).

## Consequences

- A tau pane in herdr shows what it is working on and what it has
  spent, at the cost of one queued fire-and-forget report per turn
  and per prompt.
- Cumulative cost is per-runtime-lifetime for the pane: a resumed
  session restarts the meter.
  Tau does not expose historical session cost to extensions; showing
  since-attach numbers honestly beats guessing.
- `ctx` reflects the last request's context, not a running total —
  it answers "how full is this session", which a sum would not.
