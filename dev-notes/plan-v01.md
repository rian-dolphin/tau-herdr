# Implementation plan for v0.1

Read `spec.md` first.

## Step 1 — `_env.py`

A frozen dataclass `HerdrEnv` with `pane_id`, `socket_path`, `label`.
`HerdrEnv.from_environ(environ) -> HerdrEnv | None`.
Return `None` when `HERDR_ENV != "1"`, when `HERDR_PANE_ID` or
`HERDR_SOCKET_PATH` is missing, or when `TAU_HERDR_DISABLE=1`.
`label` comes from `TAU_HERDR_AGENT_LABEL`, else `HERDR_AGENT_LABEL`,
else `tau`.

## Step 2 — `client.py`

```python
async def call(socket_path, method, params, *, timeout=0.5) -> dict | None
```

- `asyncio.open_unix_connection`, write one JSON line
  (`id = f"tau-herdr:{time.time_ns()}"`), read one response line, close.
- Whole call wrapped in `asyncio.wait_for(..., timeout)`.
- Return the parsed response dict, or `None` on any failure.
- Never raises.

## Step 3 — `extension.py`

A small `_Reporter` class holds `HerdrEnv`, a FIFO queue of pending
requests, one lazily started worker task, the last assigned `seq`, and
mutable status for `/herdr` (last state, last call ok).
The worker holds only env values; it never touches the extension API or
context (they go stale after `/reload`).

`setup(tau)`:

1. `env = HerdrEnv.from_environ(os.environ)`; return if `None`.
2. Subscribe (handlers only enqueue; they never await the socket):
   - `session_start` → enqueue `idle`; when `context.session_id` is not
     `None`, also enqueue `pane.report_agent_session` with
     `agent_session_id` and `session_start_source=event.reason`.
   - `agent_start` → enqueue `working`.
   - `agent_settled` → enqueue `idle`.
   - `session_shutdown` (every reason) → drain the queue with a bounded
     wait (1 s, plus 0.5 s for the release call); on reason `quit`, also send
     `pane.release_agent` (params include `agent`) before returning.
3. `seq` is assigned at enqueue time:
   `seq = max(last_seq + 1, time.time_ns())`.
4. Register `/herdr`: sync handler
   `(args, ExtensionCommandContext) -> str` that returns pane id,
   socket path, label, last reported state, last call success.
   No toast warnings anywhere.

All event handlers use the per-dispatch `context` argument (not a
captured reference) and never raise.

## Step 4 — tests

- Fake herdr: `asyncio.start_unix_server` in the test, recording every
  JSON line and answering `{"id": ..., "result": {"type": "ok"}}`.
- Load the real manifest with Tau's `ExtensionRuntime`
  (`extra_paths=(repo_root,)`, `include_resource_dirs=False`) and a
  patched environment.
  Bind a recording/fake session (`runtime.bind(...)`) so
  `context.session_id` resolves.
- Drive events directly: `await runtime.emit_session_start("startup")`,
  `await runtime.emit_event(AgentStartEvent())`,
  `await runtime.emit_event(AgentSettledEvent())`,
  `await runtime.emit_session_shutdown("quit")`.
  No `CodingSession` needed.
- The runtime swallows handler exceptions into diagnostics, so every
  test must assert `runtime.diagnostics == ()`.
- Await the drain (or the shutdown path) before asserting on the fake
  server's recorded lines.
- Cases: dormant outside herdr; dormant when disabled; state sequence
  for session_start/agent_start/agent_settled; session id skipped when
  `None`; release only on quit and after the queue drains; socket down
  → no exception, no diagnostics; seq strictly increasing; `/herdr`
  output via `runtime.build_command_registry()`.

## Step 5 — README + polish

- README: what it does, install (`tau -e ./tau-herdr` or clone into
  `~/.tau/extensions/`), configuration table, how it works, v0.2
  roadmap pointer.
- Run pytest; manually smoke-test inside herdr with
  `tau -e ./tau-herdr` and watch `herdr agent list`.

## Commit points

1. Scaffold + spec + ADRs (docs only).
2. Implementation + tests.
3. README + any review fixes.
