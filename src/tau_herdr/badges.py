"""Pane badges: title from the prompt, model/ctx/cost tokens (ADR 0004)."""

from __future__ import annotations

_TITLE_LIMIT = 60


def title_from_prompt(text: str) -> str | None:
    """First line of the prompt, truncated; `None` when there is none."""
    stripped = text.strip()
    if not stripped:
        return None
    line = stripped.splitlines()[0].strip()
    if len(line) <= _TITLE_LIMIT:
        return line
    return line[: _TITLE_LIMIT - 1] + "…"


def compact_count(n: int) -> str:
    if n < 1000:
        return str(n)
    if round(n / 1000, 1) < 1000:
        return f"{n / 1000:.1f}k".replace(".0k", "k")
    return f"{n / 1_000_000:.1f}M".replace(".0M", "M")


class BadgeTracker:
    """Accumulates session cost and formats per-turn badge tokens."""

    def __init__(self) -> None:
        self.cost_total = 0.0

    def reset(self) -> None:
        self.cost_total = 0.0

    def turn_tokens(self, usage) -> dict[str, str | None]:
        """Badge tokens for one finished turn.

        `ctx` is the last request's context size — how full the session
        is, not a running sum. The expression mirrors tau's own context
        meter (`provider_context_tokens`). `cost` accumulates; `None`
        (which clears the badge) while providers report no cost.
        """
        context_size = usage.total_tokens or (
            usage.input + usage.output + usage.cache_read + usage.cache_write
        )
        self.cost_total += usage.cost.total
        return {
            "ctx": compact_count(context_size),
            "cost": f"${self.cost_total:.2f}" if self.cost_total > 0 else None,
        }
