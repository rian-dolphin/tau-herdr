# tau-herdr specification (v0.1)

## Goal

Make a Tau session visible to herdr (herdr.dev), the terminal workspace
manager for AI coding agents.
herdr cannot detect Tau natively: Tau is not one of herdr's built-in agent
kinds and herdr has no detection profile for it.
Without this extension a Tau pane shows as a plain terminal.
With it, herdr shows the pane as a `tau` agent with live working/idle
state, so `herdr agent list`, `herdr agent wait`, tab-title status marks,
and notification rules all work for Tau panes.

## Scope of v0.1: self-report only

The extension reports Tau's own state to herdr.
It does not add LLM-facing tools.

State mapping (Tau extension events → herdr):

| Tau event | herdr call | State |
| --- | --- | --- |
| `session_start` (all reasons) | `pane.report_agent` + `pane.report_agent_session` | `idle`, plus session id |
| `agent_start` | `pane.report_agent` | `working` |
| `agent_settled` | `pane.report_agent` | `idle` |
| `session_shutdown` (reason `quit` only) | `pane.release_agent` | releases authority |

Notes:

- `agent_settled` is the correct idle signal, not `agent_end`.
  It fires exactly once per started run, after retries, compaction, and
  continuations, even when the frontend cancelled the run.
- `session_shutdown` also fires with reasons `reload`, `new`, `resume`,
  and `branch` on the outgoing runtime.
  We only release on `quit`.
  For the other reasons the next `session_start` re-reports.
- `pane.report_agent_session` carries `agent_session_id`
  (`tau.context.session_id`) and `session_start_source` (the reason), so
  herdr can associate the pane with the Tau session.
  When `session_id` is `None` we skip this call; we never send a null
  id.
- There is no `blocked` mapping in v0.1.
  Tau has no ask-user or permission event an extension can observe.

## Transport: Unix socket, direct

We connect to `HERDR_SOCKET_PATH` with asyncio and send one
newline-delimited JSON request per call:

```json
{"id": "tau-herdr:<time_ns>", "method": "pane.report_agent",
 "params": {"pane_id": "...", "source": "tau-herdr", "agent": "tau",
            "state": "working", "seq": <time_ns>}}
```

- This matches herdr's own reference integrations (the Claude hook ships
  the same shape from a python3 heredoc).
- No subprocess spawn on the hot path: Tau dispatches extension handlers
  sequentially with no timeout, so a blocking `herdr` CLI call would
  stall the agent loop.
- Handlers never await the socket.
  Tau awaits every handler inline on the run's critical path, so a
  0.5 s socket call in `agent_start` would delay run start and every
  downstream listener.
  Handlers enqueue a report; a single worker task sends them FIFO.
- Timeout 0.5 s per call.
  Every call is wrapped in `except Exception`; a report never raises and
  never blocks a run.
- `seq` is assigned at enqueue time as
  `seq = max(last_seq + 1, time.time_ns())`.
  The clock seed survives restarts; the increment keeps ordering strict
  even inside one nanosecond tick.
- On `session_shutdown` (every reason) the handler drains the queue
  with a bounded wait (1 s, plus 0.5 s for the release call on `quit`).
  The process exits right after `quit`, so a fire-and-forget release
  would never be sent, and a queued `idle` arriving after the release
  would resurrect the pane.
- The worker holds only the env values and socket path.
  It never touches the extension API or context, which go stale after
  `/reload`.
- `pane.release_agent` requires `pane_id`, `source`, and `agent`
  (verified against herdr 0.8.0; `agent` missing is an
  `invalid_request`).

## Activation

`setup(tau)` checks the environment once:

- Requires `HERDR_ENV=1`, `HERDR_PANE_ID`, and `HERDR_SOCKET_PATH`.
- If any is missing, `setup` returns without subscribing anything.
  Outside herdr the extension is inert: no warnings, no tools, no cost.
- `TAU_HERDR_DISABLE=1` turns the extension off inside herdr.
- The agent label is `TAU_HERDR_AGENT_LABEL`, else `HERDR_AGENT_LABEL`
  (herdr can set this itself), else `tau`.

If herdr's socket is unreachable we stay silent and keep trying on
later events.
A toast mid-run is not actionable; `/herdr` surfaces the failure
instead.

## Pane badges (added in v0.3, ADR 0004)

Display-only metadata rides the same queue via
`pane.report_metadata`:

- `title`: first line of the latest interactive prompt (60 chars);
  cleared on every `session_start`.
- Tokens: `model` (refreshed on `session_start` and `turn_end`),
  `ctx` (last assistant message's context size, compact), and `cost`
  (accumulated session cost, omitted while zero; the accumulator
  resets on `session_start`).

## `/herdr` command

Tau has no status-line API for extensions, so a `/herdr` slash command
replaces pi-herdr's footer: it returns the pane id, socket path, label,
the last reported state, and whether the last report succeeded.
The command handler is sync and returns the text
(`register_command` shows it in a modal).

## Configuration

Environment variables only, mirroring pi-herdr's approach:

| Variable | Effect |
| --- | --- |
| `TAU_HERDR_DISABLE=1` | disable the extension |
| `TAU_HERDR_AGENT_LABEL` | reported agent label (default `tau`) |

## Out of scope for v0.1 (planned v0.2+)

- LLM-facing orchestration tools (`herdr_start_agent`,
  `herdr_send_prompt`, `herdr_wait_agent`, `herdr_read_agent`,
  worktree helpers, `herdr_delegate`).
  v0.1 unblocks these: once Tau self-reports, an orchestrator can
  already `pane split` + `pane run tau` and `agent wait` on the pane.
- `blocked` state bridging (needs an ask-user seam in Tau first).
- Layout / tab / workspace tools.

## Module layout

```
tau-herdr/
  pyproject.toml            # [tool.tau] extensions = ["src/tau_herdr/extension.py"]
  src/tau_herdr/
    extension.py            # setup(tau): env gate, subscriptions, /herdr command
    client.py               # async socket call(); never raises
    _env.py                 # env detection dataclass
  tests/
  dev-notes/adr/
  README.md
```

Imports between sibling modules must be relative: Tau loads the manifest
entry under a synthetic module name and never touches `sys.path`.

## Verified by spike (2026-08-17, herdr 0.8.0, protocol 19)

- `pane.report_agent` with free-form label `tau` on an undetected pane
  makes it appear in `herdr agent list` with `agent_status: working`.
- `pane.report_agent_session` accepts a Tau session id.
- `pane.release_agent` needs the `agent` field.
