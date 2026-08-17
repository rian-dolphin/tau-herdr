# Implementation plan for v0.1

Read `spec.md` first.

## Step 1 — `_env.py`

A frozen dataclass `HerdrEnv` with `pane_id`, `socket_path`, `label`.
`HerdrEnv.from_environ(environ) -> HerdrEnv | None`.
Return `None` when `HERDR_ENV != "1"`, when `HERDR_PANE_ID` or
`HERDR_SOCKET_PATH` is missing, or when `TAU_HERDR_DISABLE=1`.
`label` comes from `TAU_HERDR_AGENT_LABEL`, default `tau`.

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

A small `_Reporter` class holds `HerdrEnv` plus mutable status for
`/herdr`: last state reported, whether the last call reached the
socket, and whether we already warned.

`setup(tau)`:

1. `env = HerdrEnv.from_environ(os.environ)`; return if `None`.
2. Subscribe:
   - `session_start` → report `idle`, then `pane.report_agent_session`
     with `agent_session_id=context.session_id` and
     `session_start_source=event.reason`.
   - `agent_start` → report `working`.
   - `agent_settled` → report `idle`.
   - `session_shutdown` → if `event.reason == "quit"`, call
     `pane.release_agent` (params include `agent`).
3. Register `/herdr` command: print pane/tab/workspace ids, label,
   last reported state, last call success.
4. On the first failed report, `tau.notify(..., "warning")` once, only
   when the host has a UI.

All handlers are `async`, use the per-dispatch `context` argument (not
a captured reference), and never raise.

## Step 4 — tests

- Fake herdr: `asyncio.start_unix_server` in the test, recording every
  JSON line and answering `{"id": ..., "result": {"type": "ok"}}`.
- Load the real manifest with Tau's `ExtensionRuntime`
  (`extra_paths=(repo_root,)`, `include_resource_dirs=False`) and a
  patched environment.
- Cases: dormant outside herdr; dormant when disabled; state sequence
  for session_start/agent_start/agent_settled; release only on quit;
  socket down → no exception, one warning; seq monotonicity;
  `/herdr` output.
- Follow the harness patterns in tau's
  `website/content/guides/extensions.md` and tau-subagents' tests.

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
