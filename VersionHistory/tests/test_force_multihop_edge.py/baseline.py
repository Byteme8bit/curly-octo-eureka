"""Force trade must not double-gate profitable multi-hop routes."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from bot.risk import RiskManager


class _RiskState:
    last_trade_at = None
    session_started_at = "2026-06-16T00:00:00+00:00"
    paused_until = None
    trades_this_hour = 0
    hour_window_start = None
    adaptive_suspended = False
    adaptive_suspended_at = None
    adaptive_relax_attempts = 0
    adaptive_alert_sent = False
    leader_symbol = "ETH/USD"
    leader_since = "2026-06-16T00:00:00+00:00"


def test_multihop_positive_net_passes_approve_action() -> None:
    risk = RiskManager(
        _RiskState(),
        fee_rate=0.0026,
        drawdown_hibernate_pct=0.15,
        hibernate_hours=12,
        trade_cooldown_seconds=0,
        max_trades_per_hour=100,
        min_trade_edge=0.002,
        leader_stable_seconds=0,
        fee_safety_multiplier=2.0,
        idle_reeval_hours=2,
        idle_reeval_max_attempts=3,
        min_net_profit_pct=0.0001,
        stat_arb_zscore_threshold=2.5,
        save_callback=lambda: None,
        profit_only_mode=True,
    )
    gate = risk.approve_action(
        "buy",
        edge=0.00201,
        trade_usd=50.0,
        is_held_swap=True,
        hops=4,
    )
    assert gate.allowed, gate.reason


def test_single_hop_swap_still_blocked_below_hurdle() -> None:
    risk = RiskManager(
        _RiskState(),
        fee_rate=0.0026,
        drawdown_hibernate_pct=0.15,
        hibernate_hours=12,
        trade_cooldown_seconds=0,
        max_trades_per_hour=100,
        min_trade_edge=0.006,
        leader_stable_seconds=600,
        fee_safety_multiplier=2.0,
        idle_reeval_hours=2,
        idle_reeval_max_attempts=3,
        min_net_profit_pct=0.0001,
        stat_arb_zscore_threshold=2.5,
        save_callback=lambda: None,
    )
    gate = risk.approve_action(
        "buy",
        edge=0.002,
        trade_usd=50.0,
        is_held_swap=True,
        hops=1,
    )
    assert not gate.allowed
    assert "Swap edge" in gate.reason
