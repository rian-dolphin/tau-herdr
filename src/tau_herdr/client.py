"""Newline-delimited JSON client for the herdr Unix socket.

One request, one response line, one connection per call — the same
shape herdr's own reference integrations use. `call` never raises.
"""

from __future__ import annotations

import asyncio
import json
import time

DEFAULT_TIMEOUT = 0.5


class HerdrError(RuntimeError):
    """A failed herdr request; the message is written for the model."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"herdr error ({code}): {message}")
        self.code = code
        self.message = message


async def request(
    socket_path: str,
    method: str,
    params: dict[str, object],
    *,
    timeout: float,
) -> dict[str, object]:
    """Send one request and return the `result` payload.

    Raises `HerdrError` on an error envelope, an unreachable socket, or
    a timeout — unlike `call()`, which swallows failures (self-report
    must never disturb Tau, but a tool must explain what went wrong).
    """
    try:
        response = await asyncio.wait_for(_call(socket_path, method, params), timeout)
    except HerdrError:
        raise
    except Exception as error:
        raise HerdrError(
            "herdr_unreachable",
            f"could not reach the herdr server at {socket_path}: {error!r}. "
            "Is herdr running?",
        ) from error
    if response is None:
        raise HerdrError(
            "herdr_unreachable",
            "the herdr server closed the connection without replying",
        )
    error_body = response.get("error")
    if isinstance(error_body, dict):
        raise HerdrError(
            str(error_body.get("code", "unknown")),
            str(error_body.get("message", "")),
        )
    result = response.get("result")
    return result if isinstance(result, dict) else {}


async def call(
    socket_path: str,
    method: str,
    params: dict[str, object],
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, object] | None:
    """Send one request to the herdr socket.

    Returns the parsed response, or `None` on any failure (unreachable
    socket, timeout, malformed response). Never raises.
    """
    try:
        return await asyncio.wait_for(
            _call(socket_path, method, params), timeout
        )
    except Exception:
        return None


async def _call(
    socket_path: str, method: str, params: dict[str, object]
) -> dict[str, object] | None:
    reader, writer = await asyncio.open_unix_connection(socket_path)
    try:
        request = {
            "id": f"tau-herdr:{time.time_ns()}",
            "method": method,
            "params": params,
        }
        writer.write(json.dumps(request).encode() + b"\n")
        await writer.drain()
        line = await reader.readline()
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
    if not line:
        return None
    parsed = json.loads(line)
    return parsed if isinstance(parsed, dict) else None
