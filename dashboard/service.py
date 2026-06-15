"""Aggregate dashboard views for API responses."""

from __future__ import annotations

from dashboard.config import DashboardSettings, load_settings
from dashboard.io_util import read_text
from dashboard.parsers import build_auditor_view, build_goals_view, build_tradebot_view, build_watchdog_view, build_whale_view
from dashboard.parsers.series import build_forecasts, build_portfolio_history, build_trades_series
from dashboard.parsers.timeline import build_timeline

VALID_MODES = frozenset({"paper", "live"})


def normalize_mode(mode: str | None) -> str:
    normalized = (mode or "paper").lower()
    return normalized if normalized in VALID_MODES else "paper"


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


def _build_summary_strip(tradebot: dict, watchdog: dict, *, mode: str) -> dict:
    p = tradebot.get("portfolio") or {}
    guard = tradebot.get("live_guardrails") or {}
    h = watchdog.get("health") or {}
    s = watchdog.get("session") or {}
    pnl = p.get("baseline_pnl")
    base = {
        "trading_mode": mode,
        "portfolio_usd": p.get("portfolio_usd"),
        "baseline_pnl": pnl,
        "drawdown_pct": p.get("drawdown_pct"),
        "cash_pct": p.get("cash_pct"),
        "trade_count": p.get("trade_count", 0),
        "health_score": h.get("score"),
        "trades_session": s.get("trades_session", 0),
        "updated_at": p.get("updated_at"),
        "anchored_at": p.get("anchored_at"),
    }
    if mode == "live":
        base.update({
            "peak_portfolio_usd": p.get("peak_portfolio_usd"),
            "halted": guard.get("halted", False),
            "halt_reasons": guard.get("halt_reasons") or [],
            "eth_balance": guard.get("eth_balance"),
            "eth_floor": guard.get("eth_floor"),
            "drawdown_halt_pct": guard.get("drawdown_halt_pct"),
            "max_trades": guard.get("max_trades"),
            "trades_completed": guard.get("trades_completed"),
            "trades_remaining": guard.get("trades_remaining"),
        })
    return base


def build_overview(settings: DashboardSettings | None = None, *, mode: str = "paper") -> dict:
    cfg = settings or load_settings()
    dashboard_mode = normalize_mode(mode)
    tradebot = build_tradebot_view(cfg, mode=dashboard_mode)
    drawdown = 0.0
    if tradebot.get("portfolio"):
        drawdown = float(tradebot["portfolio"].get("drawdown_pct", 0.0))
    watchdog = build_watchdog_view(cfg, drawdown_pct=drawdown)
    auditor = build_auditor_view(cfg)
    whales = build_whale_view(cfg)
    goals = build_goals_view(cfg, mode=dashboard_mode)
    forecasts = build_forecasts(cfg)
    timeline = build_timeline(
        cfg,
        tradebot=tradebot,
        watchdog=watchdog,
        auditor=auditor,
        limit=25,
    )
    guard = tradebot.get("live_guardrails") or {}
    dual_summary = None
    if cfg.live_mirror_paper and cfg.live_enabled:
        paper_tb = build_tradebot_view(cfg, mode="paper")
        live_tb = build_tradebot_view(cfg, mode="live")
        paper_wd = build_watchdog_view(
            cfg,
            drawdown_pct=float((paper_tb.get("portfolio") or {}).get("drawdown_pct", 0.0)),
        )
        live_wd = build_watchdog_view(
            cfg,
            drawdown_pct=float((live_tb.get("portfolio") or {}).get("drawdown_pct", 0.0)),
        )
        dual_summary = {
            "paper": _build_summary_strip(paper_tb, paper_wd, mode="paper"),
            "live": _build_summary_strip(live_tb, live_wd, mode="live"),
        }
    return {
        "mode": dashboard_mode,
        "mirror_mode": cfg.live_mirror_paper and cfg.live_enabled,
        "live_enabled": cfg.live_enabled,
        "refresh_seconds": cfg.refresh_seconds,
        "root": str(cfg.root),
        "summary": _build_summary_strip(tradebot, watchdog, mode=dashboard_mode),
        "tradebot": tradebot,
        "watchdog": watchdog,
        "auditor": auditor,
        "whales": whales,
        "goals": goals,
        "forecasts": forecasts,
        "timeline": timeline,
        "live_guardrails": guard if dashboard_mode == "live" else None,
        "dual_summary": dual_summary,
        "backlog": _backlog_snippet(cfg.backlog_file),
    }
