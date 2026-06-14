"""Tests for live portfolio dashboard parser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dashboard.config import DashboardSettings
from dashboard.parsers.live_portfolio import load_live_portfolio
from dashboard.parsers.tradebot import build_tradebot_view


def _settings(root: Path, *, live: bool = False) -> DashboardSettings:
    return DashboardSettings(
        root=root,
        host="127.0.0.1",
        port=8765,
        refresh_seconds=15,
        paper_portfolio_file=root / "paper_portfolio.json",
        paper_state_file=root / ".paper_state.json",
        watchdog_state_file=root / ".watchdog_state.json",
        auditor_state_file=root / ".auditor_state.json",
        runtime_overrides_file=root / "runtime_overrides.json",
        log_dir=root / "logs",
        runtime_log=root / "logs/runtime.log",
        discord_chat_log=root / "logs/discord_chat.log",
        receipts_dir=root / "receipts",
        reports_dir=root / "reports",
        backlog_file=root / "BACKLOG.md",
        whale_watch_state_file=root / ".whale_watch_state.json",
        goal_state_file=root / ".tradebot_goals_state.json",
        live_enabled=live,
        live_mirror_paper=False,
        live_state_file=root / ".live_state.json",
        live_session_start_file=root / "live_session_start.json",
        error_burst_count=5,
        error_burst_minutes=10.0,
        auto_pause_score=25,
    )


def test_load_live_portfolio_day_zero(tmp_path: Path):
    session = {
        "anchored_at_pacific": "2026-06-13 20:26:30 PDT",
        "baseline_portfolio_usd": 1653.94,
        "peak_portfolio_usd": 1653.94,
        "balances": {"ETH": 0.96409885, "USD": 17.9999, "ADA": 83.9640169},
        "usd_prices": {"USD": 1.0, "ETH": 1681.45, "ADA": 0.172953},
    }
    (tmp_path / "live_session_start.json").write_text(
        json.dumps(session), encoding="utf-8"
    )
    (tmp_path / ".live_state.json").write_text(
        json.dumps(
            {
                "balances": session["balances"],
                "risk": {
                    "baseline_portfolio": 1653.94,
                    "peak_portfolio": 1653.94,
                    "live_trades_completed": 0,
                },
                "trades": [],
            }
        ),
        encoding="utf-8",
    )

    live = load_live_portfolio(_settings(tmp_path, live=True))
    assert live is not None
    assert live["mode"] == "live"
    assert live["baseline_portfolio_usd"] == pytest.approx(1653.94)
    assert live["peak_portfolio_usd"] == pytest.approx(1653.94)
    assert live["drawdown_pct"] == pytest.approx(0.0, abs=0.01)
    assert live["trade_count"] == 0
    assert any(h["asset"] == "ETH" for h in live["holdings"])


def test_build_tradebot_view_uses_live_mode(tmp_path: Path):
    session = {
        "anchored_at_pacific": "2026-06-13 20:26:30 PDT",
        "baseline_portfolio_usd": 1653.94,
        "peak_portfolio_usd": 1653.94,
        "balances": {"ETH": 0.96409885, "USD": 18.0},
        "usd_prices": {"USD": 1.0, "ETH": 1681.45},
    }
    (tmp_path / "live_session_start.json").write_text(json.dumps(session), encoding="utf-8")
    (tmp_path / ".live_state.json").write_text(
        json.dumps(
            {
                "balances": session["balances"],
                "risk": {
                    "baseline_portfolio": 1653.94,
                    "peak_portfolio": 1653.94,
                    "live_trades_completed": 0,
                },
                "trades": [],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "paper_portfolio.json").write_text(
        json.dumps(
            {
                "portfolio_usd": 999.0,
                "baseline_pnl": -50.0,
                "drawdown_pct": 0.05,
                "holdings": {},
            }
        ),
        encoding="utf-8",
    )

    view = build_tradebot_view(_settings(tmp_path, live=True))
    assert view["mode"] == "live"
    assert view["portfolio"]["portfolio_usd"] != 999.0
    assert view["portfolio"]["trade_count"] == 0
