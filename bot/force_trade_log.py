"""File log for Discord ``TradeBot -force`` attempts."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def format_force_trade_line(
    *,
    outcome: str,
    detail: str,
) -> str:
    from bot.local_time import format_pacific

    ts = format_pacific()
    return f"{ts} {outcome} {detail}"


def append_force_trade_log(path: Path, *, outcome: str, detail: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = format_force_trade_line(outcome=outcome, detail=detail)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as exc:
        logger.warning("Could not write force-trade log (%s): %s", path, exc)
