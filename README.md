# tau-herdr

A [Tau](https://twotimespi.dev) extension that integrates with
[herdr](https://herdr.dev), the terminal workspace manager for AI
coding agents: it reports Tau's state to herdr, and ships a skill for
orchestrating the rest of the workspace.

herdr cannot detect Tau natively — a Tau pane normally shows up as a
plain terminal. With this extension the pane appears in
`herdr agent list` as a `tau` agent with live state, so `herdr agent
wait`, tab-title status marks, and herdr's notification rules all work
for Tau sessions.

## What it reports

| Tau moment | herdr sees |
| --- | --- |
| session starts (or resumes, branches, reloads) | `idle`, plus the Tau session id |
| a run starts | `working` |
| the run settles (after retries, compaction, continuations) | `idle` |
| Tau quits | the pane's agent authority is released |

The pane also gets live badges: its title becomes the latest prompt,
and `model` / `ctx` (context size) / `cost` (session spend) tokens
update after every turn.

Reports go straight to herdr's Unix socket (`HERDR_SOCKET_PATH`) as
newline-delimited JSON — no subprocess, nothing on the agent loop's hot
path, and a dead herdr server never breaks Tau.

## Install

```bash
git clone git@github.com:rian-dolphin/tau-herdr.git
tau -e ./tau-herdr
```

Or make it permanent by cloning into `~/.tau/extensions/`.

Outside a herdr pane the extension is inert: it registers nothing and
costs nothing.

## Usage

There is nothing to do — start `tau` inside a herdr pane and the pane
starts reporting. The `/herdr` slash command shows the integration
status: pane id, socket path, label, the last reported state, and
whether the last report reached herdr.

## Orchestration: the `herdr` skill

By default the extension adds **nothing** to Tau's system prompt — no
tools, no guidelines. Orchestration is on demand, as a skill
(one name+description line in the prompt, full content only when
used):

```bash
ln -s /path/to/tau-herdr/skills/herdr ~/.tau/skills/herdr
```

Then invoke it with `/skill:herdr` (or just ask — *"use the herdr
skill to spawn a claude agent in a new worktree, run the tests, and
notify me when it's done"*). The skill teaches Tau to drive the
`herdr` CLI from the shell: spawning and prompting agents in panes,
running commands in separate terminals, worktrees, and notifications —
including the tau-specific edges (there is no `tau` agent kind, and
self-reported panes need typed prompts).

An earlier version shipped the orchestration surface as 22 native
tools; it was removed to keep one maintainable path (see
`dev-notes/adr/0006`). The last release with it is tag
[`v0.4.0`](https://github.com/rian-dolphin/tau-herdr/tree/v0.4.0).

## Configuration

Environment variables only:

| Variable | Effect |
| --- | --- |
| `TAU_HERDR_DISABLE=1` | disable the extension |
| `TAU_HERDR_AGENT_LABEL` | reported agent label (default: `HERDR_AGENT_LABEL`, else `tau`) |

## Development

Design records live in `dev-notes/` (spec, plan, ADRs). Tests drive
Tau's real `ExtensionRuntime` against a fake herdr socket server:

```bash
uv run --project /path/to/tau pytest tests/
```

## Roadmap

Future candidates: a herdr detection manifest for tau (native
`agent.start --kind tau`), push-based waiting via `events.subscribe`,
and a `blocked` state once tau exposes an ask-user event to
extensions.
