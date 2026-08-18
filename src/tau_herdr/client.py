"""Newline-delimited JSON client for the herdr Unix socket.

One request, one response line, one connection per call — the same
shape herdr's own reference integrations use. `call` never raises.
"""

from __future__ import annotations

import asyncio
import json
import time

DEFAULT_TIMEOUT = 0.5


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
