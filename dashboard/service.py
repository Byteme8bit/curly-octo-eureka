"""Aggregate dashboard views for API responses."""

from __future__ import annotations

from dashboard.config import DashboardSettings, load_settings
from dashboard.io_util import read_text
from dashboard.parsers import build_auditor_view, build_goals_view, build_tradebot_view, build_watchdog_view, build_whale_view
from dashboard.parsers.series import build_forecasts, build_portfolio_history, build_trades_series
from dashboard.parsers.timeline import build_timeline


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


def _build_summary_strip(tradebot: dict, watchdog: dict) -> dict:
    p = tradebot.get("portfolio") or {}
    h = watchdog.get("health") or {}
    s = watchdog.get("session") or {}
    pnl = p.get("baseline_pnl")
    return {
        "portfolio_usd": p.get("portfolio_usd"),
        "baseline_pnl": pnl,
        "drawdown_pct": p.get("drawdown_pct"),
        "cash_pct": p.get("cash_pct"),
        "trade_count": p.get("trade_count", 0),
        "health_score": h.get("score"),
        "trades_session": s.get("trades_session", 0),
        "updated_at": p.get("updated_at"),
    }


def build_overview(settings: DashboardSettings | None = None) -> dict:
    cfg = settings or load_settings()
    tradebot = build_tradebot_view(cfg)
    drawdown = 0.0
    if tradebot.get("portfolio"):
        drawdown = float(tradebot["portfolio"].get("drawdown_pct", 0.0))
    watchdog = build_watchdog_view(cfg, drawdown_pct=drawdown)
    auditor = build_auditor_view(cfg)
    whales = build_whale_view(cfg)
    goals = build_goals_view(cfg)
    forecasts = build_forecasts(cfg)
    timeline = build_timeline(
        cfg, tradebot=tradebot, watchdog=watchdog, auditor=auditor, limit=25
    )
    return {
        "refresh_seconds": cfg.refresh_seconds,
        "root": str(cfg.root),
        "summary": _build_summary_strip(tradebot, watchdog),
        "tradebot": tradebot,
        "watchdog": watchdog,
        "auditor": auditor,
        "whales": whales,
        "goals": goals,
        "forecasts": forecasts,
        "timeline": timeline,
        "backlog": _backlog_snippet(cfg.backlog_file),
    }
