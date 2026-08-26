---
title: "ADR 0004 — Pane title and model/ctx/cost tokens"
---

## Status

Accepted; amended to use Tau session names for titles

## Context

herdr shows display-only pane metadata reported through
`pane.report_metadata`: a pane `title`, up to 16 named string
`tokens`, per-status `state_labels`, and a `display_agent`.
herdr-managed agents (claude, codex) get useful titles because their
CLIs set the terminal title themselves.
Tau generates a concise name for each session.
Tau 0.4.0 exposes this name to extensions through
`context.session_name` and `session_info_changed`.
Tau also exposes the model (`context.model`) and per-turn `Usage` with
token counts and USD cost (`turn_end`).

An earlier version used the first line of each prompt as the title.
We removed that behavior because it exposed prompt text and changed the
title on every prompt.

## Decision

Report the title and tokens through the existing self-report queue.
They share one `seq` and one shutdown drain:

- Title: from `context.session_name` on `session_start`.
  Clear a stale title when the session has no name.
  Update the title on `session_info_changed`.
  Use `getattr` so Tau versions before 0.4.0 continue without a title.
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

- A Tau pane shows the stable, concise session name without exposing
  prompt text.
- The reported title has priority over a manual herdr pane label while
  Tau is active.
- A title change adds one queued fire-and-forget report.
- Cumulative cost is per-runtime-lifetime for the pane: a resumed
  session restarts the meter.
  Tau does not expose historical session cost to extensions; showing
  since-attach numbers honestly beats guessing.
- `ctx` reflects the last request's context, not a running total —
  it answers "how full is this session", which a sum would not.
