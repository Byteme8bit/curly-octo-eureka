"""Aggregate dashboard views for API responses."""

from __future__ import annotations

from dashboard.config import DashboardSettings, load_settings
from dashboard.io_util import read_text
from dashboard.parsers import build_auditor_view, build_tradebot_view, build_watchdog_view


def _backlog_snippet(path, *, max_lines: int = 12) -> list[str]:
    raw = read_text(path)
    if not raw:
        return []
    lines = []
    for line in raw.splitlines():
        if line.strip().startswith("- "):
            lines.append(line.strip())
        if len(lines) >= max_lines:
            break
    return lines


def build_overview(settings: DashboardSettings | None = None) -> dict:
    cfg = settings or load_settings()
    tradebot = build_tradebot_view(cfg)
    drawdown = 0.0
    if tradebot.get("portfolio"):
        drawdown = float(tradebot["portfolio"].get("drawdown_pct", 0.0))
    watchdog = build_watchdog_view(cfg, drawdown_pct=drawdown)
    auditor = build_auditor_view(cfg)
    return {
        "refresh_seconds": cfg.refresh_seconds,
        "root": str(cfg.root),
        "tradebot": tradebot,
        "watchdog": watchdog,
        "auditor": auditor,
        "backlog": _backlog_snippet(cfg.backlog_file),
    }
