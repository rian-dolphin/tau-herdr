# tau-herdr specification (v0.2 — orchestration tools)

Read `spec.md` (v0.1, self-report) first.
v0.2 adds LLM-facing tools that let the Tau agent drive herdr:
spawn and prompt other agents, run commands in panes, manage layout,
create git worktrees, and send notifications.
The tool names follow pi-herdr where a tool has a pi-herdr
equivalent.

## Transport

Tools use the same Unix socket as self-report.
`client.py` gains a second entry point:

```python
async def request(socket_path, method, params, *, timeout) -> dict
```

Unlike `call()` (fire-and-forget, returns `None` on failure),
`request()` raises `HerdrError(code, message)` on an error envelope,
an unreachable socket, or a timeout.
Tau's tool loop converts any raised exception into an error tool
result, so `HerdrError` messages are written for the model.

Verified live against herdr 0.8.0 (protocol 19):

- There is no socket `pane.run`.
  The equivalent is `pane.send_input {pane_id, text, keys: ["Enter"]}`.
- There are no socket session list/stop/delete methods.
  Those pi-herdr tools are cut.
- `agent.start` takes a closed `kind` enum of 21 kinds.
  `tau` is not one of them.
  Starting a tau pane means `pane.split` + `pane.send_input("tau")`;
  the spawned Tau's own self-report (v0.1) makes it visible.
- Socket read `source` values use underscores (`recent_unwrapped`);
  we expose the CLI spelling (`recent-unwrapped`) and map on the wire.

## Cancellation and long waits

Tau's tool cancellation token is poll-only (`signal.is_cancelled()`).
Every long wait is chunked: send `timeout_ms = min(2000, remaining)`
to the server, check the token between chunks, and treat a `timeout`
error envelope from a chunk as "keep waiting", not a failure.
Never send the server one long `timeout_ms`; that makes the tool
uninterruptible.

Socket timeouts: 10 s for trivial calls (list/get/focus/rename/close/
send/notify), 15 s for reads and splits, 30 s for worktree list/open/
remove, 60 s for worktree create, chunk + 5 s slack for waits.

## Tool surface (22 tools)

### Orchestration (10)

| Tool | Socket call(s) |
| --- | --- |
| `herdr_start_agent` | `pane.split` then `agent.start` (or `pane.send_input` for `kind: tau`) |
| `herdr_send_prompt` | `agent.prompt` (submit) or `pane.send_text` (type only) |
| `herdr_wait_agent` | `agent.wait` (chunked) |
| `herdr_read_agent` | `agent.read` |
| `herdr_list_agents` | `agent.list` |
| `herdr_get_agent` | `agent.get` |
| `herdr_rename_agent` | `agent.rename` |
| `herdr_focus_agent` | `agent.focus` |
| `herdr_close_pane` | `pane.close` (resolves agent targets via `agent.get`; absorbs pi-herdr's `herdr_stop_agent`) |
| `herdr_delegate` | composite, below |

`target` params accept a pane id (`w1:p3`), agent name, or label;
the server resolves them.

### Pane sync (5)

| Tool | Socket call(s) |
| --- | --- |
| `herdr_split_pane` | `pane.split` |
| `herdr_run_command` | `pane.send_input` with `keys: ["Enter"]` |
| `herdr_read_pane` | `pane.read` |
| `herdr_wait_output` | `pane.wait_for_output` (chunked; `match` XOR `regex`) |
| `herdr_send_keys` | `pane.send_keys` |

### Layout (1 multiplexer)

`herdr_layout` with an `action` enum:
`list_panes`, `get_pane`, `move_pane`, `list_tabs`, `create_tab`,
`focus_tab`, `rename_tab`, `close_tab`, `list_workspaces`,
`create_workspace`, `focus_workspace`, `rename_workspace`,
`close_workspace`.
These are all trivial passthroughs with near-identical shapes; one
tool keeps the prompt budget sane (see ADR 0003).
`pane.move`'s destination is a tagged union
(`{type: "tab"|"new_tab"|"new_workspace", ...}`), unlike the CLI's
flat flags.

### Worktrees (4)

`herdr_worktree_create`, `herdr_worktree_open`,
`herdr_worktree_list`, `herdr_worktree_remove` →
`worktree.create/open/list/remove`.
Results include `workspace_id` and the root pane id so the caller can
immediately start an agent in the new worktree.

### Introspection and notifications (2)

- `herdr_api_snapshot` → `session.snapshot`.
  One-line text summary; the full snapshot goes in result `details`.
- `herdr_notify` → `notification.show {title, body, sound}`.

### Cut from pi-herdr, with reasons

- `herdr_explain_agent`: detection debugging, not an orchestration
  need.
- `herdr_session_list/stop/delete`: no socket method; whole-session
  destruction.
- `herdr_resize_pane`, `herdr_zoom_pane`, `herdr_swap_panes`: human
  ergonomics; an orchestrator does not need pane geometry.
- All legacy/Windows/version-probing branches: we pin protocol 19.

## `herdr_delegate`

One-shot: spawn an agent, prompt it, wait for the answer, read it,
optionally close the pane.

1. Start (as `herdr_start_agent`).
2. Boot gate: chunked `agent.wait` until `idle`, budget 90 s;
   then a 1.5 s settle sleep so the TUI input is ready.
3. Prompt: `agent.prompt` with server-side wait, chunked.
   On an `agent_prompt_stalled` error, re-send, at most 3 attempts.
4. Read: `agent.read` (`recent`, 50 lines, text).
5. Blocked check via `agent.get`:
   - `on_blocked: "return"` (default): return
     `{blocked: true, question, pane_id}` as an error result so the
     orchestrator relays the question to the user and continues with
     `herdr_send_prompt` + `herdr_wait_agent`.
   - `on_blocked: "wait"`: keep waiting in chunks (only cancellation
     stops it), then re-read.
6. `close_on_success: true` closes the pane.

Default `on_blocked` is `"return"`, diverging from pi-herdr: bounded
behavior by default, and Tau itself never reports `blocked`, so the
wait branch only matters when delegating to other agent kinds.

## Registration

Tools register in `setup()` only when the herdr env gate passes —
outside herdr Tau's prompt carries zero herdr tools.
One prompt guideline is added describing when to reach for herdr
tools.

## Deferred to v0.3+

- Pane badges (`pane.report_metadata`: tokens, state labels).
- A herdr detection manifest for tau (`agent.start --kind tau`).
- `events.subscribe` push-based waiting.
