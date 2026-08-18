# tau-herdr

A [Tau](https://twotimespi.dev) extension that integrates with
[herdr](https://herdr.dev), the terminal workspace manager for AI
coding agents: it reports Tau's state to herdr, and gives Tau a tool
surface to orchestrate the rest of the workspace.

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

## Orchestration tools

Inside herdr, Tau also gets 22 `herdr_*` tools (names follow
[pi-herdr](https://github.com/AndrewJacop/pi-herdr) where an
equivalent exists):

- **Agents** — `herdr_start_agent`, `herdr_send_prompt`,
  `herdr_wait_agent`, `herdr_read_agent`, `herdr_list_agents`,
  `herdr_get_agent`, `herdr_rename_agent`, `herdr_focus_agent`,
  `herdr_close_pane`: spawn claude/codex/gemini/…/tau agents in panes,
  prompt them, wait for them, and read their output.
- **`herdr_delegate`** — one shot: spawn an agent, prompt it, wait,
  return its answer. If the delegate asks a question, the tool errors
  with the question so Tau can relay it (or pass
  `on_blocked: "wait"`).
- **Pane sync** — `herdr_split_pane`, `herdr_run_command`,
  `herdr_read_pane`, `herdr_wait_output`, `herdr_send_keys`: raw
  terminals for builds, servers, and logs.
- **`herdr_layout`** — one multiplexer for pane/tab/workspace
  management (list, create, focus, rename, move, close).
- **Worktrees** — `herdr_worktree_create/open/list/remove`: parallel
  git checkouts opened as herdr workspaces.
- **`herdr_api_snapshot`**, **`herdr_notify`** — live session
  introspection and user notifications.

Everything talks straight to the herdr socket (protocol 19, herdr
≥ 0.8.0). Long waits are chunked so pressing Esc in Tau interrupts
them promptly. Ask Tau things like: *"spawn a claude agent in a new
worktree for the auth-refactor branch, have it run the tests, and
notify me when it's done."*

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

v0.3 candidates: pane badges (`pane.report_metadata` token/state
labels), a herdr detection manifest for tau, and push-based waiting
via `events.subscribe`.
