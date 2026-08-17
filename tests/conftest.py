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


@dataclass
class FakeHerdr:
    """A fake herdr socket server that records every request."""

    socket_path: str
    requests: list[dict] = field(default_factory=list)
    respond_error: bool = False
    hang: bool = False

    def requests_for(self, method: str) -> list[dict]:
        return [r for r in self.requests if r.get("method") == method]


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
                if server_state.respond_error:
                    response = {
                        "id": request.get("id"),
                        "error": {"code": "boom", "message": "boom"},
                    }
                else:
                    response = {"id": request.get("id"), "result": {"type": "ok"}}
                writer.write(json.dumps(response).encode() + b"\n")
                await writer.drain()
            writer.close()

        server = await asyncio.start_unix_server(handle, path=server_state.socket_path)
        try:
            yield server_state
        finally:
            server.close()
            await server.wait_closed()
