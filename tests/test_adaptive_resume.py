"""Adaptive suspension cooldown — bot must not stay stuck at strict thresholds."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from bot.paper_broker import RiskState
from bot.risk import RiskManager


def _risk_manager(*, suspended: bool = True, suspended_at: str | None = None) -> RiskManager:
    state = RiskState(
        last_trade_at=(datetime.now(timezone.utc) - timedelta(hours=6)).isoformat(),
        adaptive_suspended=suspended,
        adaptive_suspended_at=suspended_at,
    )
    return RiskManager(
        risk_state=state,
        fee_rate=0.0026,
        drawdown_hibernate_pct=0.15,
        hibernate_hours=12.0,
        trade_cooldown_seconds=0,
        max_trades_per_hour=100,
        min_trade_edge=0.0115,
        leader_stable_seconds=600,
        fee_safety_multiplier=2.0,
        idle_reeval_hours=2.0,
        idle_reeval_max_attempts=3,
        min_net_profit_pct=0.0005,
        stat_arb_zscore_threshold=2.5,
        save_callback=lambda: None,
    )


def test_adaptive_resumes_after_suspend_cooldown() -> None:
    suspended_at = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    risk = _risk_manager(suspended=True, suspended_at=suspended_at)
    status = risk.adaptive_status()
    assert status.suspended is False
    assert status.relax_factor < 1.0


def test_adaptive_stays_suspended_during_cooldown() -> None:
    suspended_at = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    risk = _risk_manager(suspended=True, suspended_at=suspended_at)
    status = risk.adaptive_status()
    assert status.suspended is True
    assert status.relax_factor == 1.0


def test_adaptive_resumes_legacy_state_without_timestamp() -> None:
    risk = _risk_manager(suspended=True, suspended_at=None)
    status = risk.adaptive_status()
    assert status.suspended is False
    assert status.relax_factor < 1.0
