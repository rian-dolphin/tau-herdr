# tau-herdr

A [Tau](https://twotimespi.dev) extension that reports the agent's state
to [herdr](https://herdr.dev), the terminal workspace manager for AI
coding agents.

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

v0.2 may add LLM-facing orchestration tools (start/prompt/read/wait on
other herdr agents, worktree helpers) in the spirit of
[pi-herdr](https://github.com/AndrewJacop/pi-herdr), which inspired
this project.
