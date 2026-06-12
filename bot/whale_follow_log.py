"""Quiet file log for whale-follow skip events."""

from __future__ import annotations

import logging
from pathlib import Path

from bot.whale_watch import WhaleEvent

logger = logging.getLogger(__name__)


def format_whale_follow_skip_line(event: WhaleEvent, reason: str) -> str:
    from bot.local_time import format_pacific

    ts = format_pacific()
    return f"{ts} {event.pair} ${event.usd_size:,.0f} {event.direction} — {reason}"


def append_whale_follow_skip(event: WhaleEvent, reason: str, path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = format_whale_follow_skip_line(event, reason)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as exc:
        logger.warning("Could not write whale-follow skip log (%s): %s", path, exc)


def read_whale_follow_skips(path: Path, *, last: int = 20) -> list[str]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    trimmed = [ln for ln in lines if ln.strip()]
    if last <= 0:
        return trimmed
    return trimmed[-last:]
