---
title: "ADR 0001 — Ship v0.1 as self-report only"
---

## Status

Accepted

## Context

pi-herdr, the inspiration for this project, has two halves.
The first half reports Pi's own state to herdr.
The second half registers 43 LLM-facing tools that let the agent drive
herdr panes, tabs, workspaces, and worktrees.
The second half is more than 1300 lines in one file alone.

herdr has no built-in detection for Tau.
Tau is not in herdr's agent-kind list.
Without self-report, a Tau pane is invisible to herdr's agent features.

Tau's design values small, readable code.

## Decision

v0.1 contains only self-report: working/idle state, session identity,
and release on quit.
We defer all LLM-facing orchestration tools to a later version.

## Consequences

- v0.1 is small (about 200 lines) and easy to review.
- A Tau pane appears in `herdr agent list` with live state.
  `herdr agent wait` and notification rules work on Tau panes.
- Self-report unblocks orchestration from the outside: any agent can
  `pane split`, `pane run tau`, and `agent wait` on the new pane.
- Users who want pi-herdr's full tool surface must wait for v0.2.

## Why diverge from pi-herdr here

pi-herdr drives *other* agents from Pi.
A user can already do that from a shell or from another integrated
agent.
The unique value for Tau is visibility, because herdr cannot detect Tau
at all.
We ship the unique value first.
