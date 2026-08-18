"""Shared fixtures for the tau-herdr test suite."""

import asyncio
import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


HERDR_ENV_VARS = (
    "HERDR_ENV",
    "HERDR_PANE_ID",
    "HERDR_SOCKET_PATH",
    "HERDR_AGENT_LABEL",
    "TAU_HERDR_DISABLE",
    "TAU_HERDR_AGENT_LABEL",
)


@pytest.fixture(autouse=True)
def _clean_herdr_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The test host may itself run inside herdr; start every test clean."""
    for name in HERDR_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@dataclass
class FakeHerdr:
    """A fake herdr socket server that records every request."""

    socket_path: str
    requests: list[dict] = field(default_factory=list)
    hang: bool = False

    def requests_for(self, method: str) -> list[dict]:
        return [r for r in self.requests if r.get("method") == method]

    def respond(self, request: dict) -> dict:
        return {"id": request.get("id"), "result": {"type": "ok"}}


@pytest.fixture
async def fake_herdr():
    # AF_UNIX socket paths are capped around 104 bytes on macOS, so the
    # socket lives in a short mkdtemp instead of pytest's tmp_path.
    with tempfile.TemporaryDirectory(prefix="tau-herdr-") as tmp:
        server_state = FakeHerdr(socket_path=str(Path(tmp) / "herdr.sock"))

        async def handle(reader, writer):
            while line := await reader.readline():
                request = json.loads(line)
                server_state.requests.append(request)
                if server_state.hang:
                    continue
                response = server_state.respond(request)
                writer.write(json.dumps(response).encode() + b"\n")
                await writer.drain()
            writer.close()

        server = await asyncio.start_unix_server(handle, path=server_state.socket_path)
        try:
            yield server_state
        finally:
            server.close()
            await server.wait_closed()
