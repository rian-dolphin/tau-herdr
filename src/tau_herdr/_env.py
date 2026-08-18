"""Detection of the herdr environment."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HerdrEnv:
    """The values tau-herdr needs from a herdr pane's environment."""

    pane_id: str
    socket_path: str
    label: str
    tools_enabled: bool

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> "HerdrEnv | None":
        """Return the herdr environment, or `None` when the extension
        should stay dormant (outside herdr, or explicitly disabled)."""
        if environ.get("HERDR_ENV") != "1":
            return None
        if environ.get("TAU_HERDR_DISABLE") == "1":
            return None
        pane_id = environ.get("HERDR_PANE_ID")
        socket_path = environ.get("HERDR_SOCKET_PATH")
        if not pane_id or not socket_path:
            return None
        label = (
            environ.get("TAU_HERDR_AGENT_LABEL")
            or environ.get("HERDR_AGENT_LABEL")
            or "tau"
        )
        return cls(
            pane_id=pane_id,
            socket_path=socket_path,
            label=label,
            tools_enabled=environ.get("TAU_HERDR_TOOLS") == "1",
        )
