---
title: "ADR 0005 — Orchestration is a skill by default, tools are opt-in"
---

## Status

Accepted; the `TAU_HERDR_TOOLS` opt-in is superseded by ADR 0006
(the tool surface is removed entirely).

## Context

v0.2 registered 22 tools and one prompt guideline in every Tau
session inside herdr.
pi-herdr goes further: it registers all 43 of its tools
unconditionally, each with its own prompt snippet.
The project owner does not want the extension to add any tools or any
system prompt by default; orchestration should be something you ask
for ("use the herdr skill"), not something every session pays for.
Tau supports the Agent Skills spec: a `SKILL.md` costs one
name-plus-description line in the prompt and loads its full content
only when invoked (`/skill:herdr`, or when the model chooses it).

## Decision

- By default the extension registers nothing the model can see: no
  tools, no prompt guideline.
  Self-report, pane badges, and the `/herdr` slash command remain —
  they cost no prompt.
- Orchestration ships as a skill (`skills/herdr/SKILL.md`) that
  teaches driving the `herdr` CLI from the shell tool, including the
  facts we learned building the tool surface: no `tau` agent kind
  (use `pane run tau`), the `agent_not_ready` typed-input fallback
  for prompting self-reported panes, boot-then-prompt-then-wait
  ordering, and the blocked-question flow.
  Install: symlink `skills/herdr` into `~/.tau/skills/`.
- `TAU_HERDR_TOOLS=1` opts into the native v0.2 tool surface for
  users who want structured tools (chunked cancellation-aware waits,
  `herdr_delegate`'s retry state machine) over CLI calls.

## Consequences

- A default Tau session inside herdr carries one skill-list line
  instead of 22 tool schemas.
- The CLI path is version-tolerant and needs no socket code from the
  model, but loses the tools' niceties: delegate's stall retry and
  seq-based prompt verification, and Esc-responsive chunked waits
  (a CLI `agent wait` blocks the shell tool until its timeout).
- The tool code stays tested; the opt-in keeps it honest.

## Why diverge from pi-herdr here

pi-herdr's always-on tool surface fits Pi's ecosystem, where
extensions routinely ship tools.
Tau treats prompt space as a scarce resource, and its skills give an
on-demand path pi-herdr did not have when it was designed.
