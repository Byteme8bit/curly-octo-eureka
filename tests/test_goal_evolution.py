"""Tests for portfolio goal milestones and crash-hold guard (feature 042)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bot.goal_evolution import (
    CrashGuardConfig,
    GoalEvolutionConfig,
    GoalEvolutionManager,
    GoalEvolutionState,
    GoalTier,
    build_manager_from_settings,
    compute_primary_goal,
    format_primary_goal_discord,
)


def _tiers() -> tuple[GoalTier, ...]:
    return (
        GoalTier(level=0, threshold_usd=0.0, label="Baseline", strategies=("cross_momentum",)),
        GoalTier(
            level=1,
            threshold_usd=10_000.0,
            label="Growth",
            strategies=("cross_momentum", "stat_arb"),
        ),
        GoalTier(
            level=2,
            threshold_usd=100_000.0,
            label="Scale",
            strategies=("cross_momentum", "stat_arb", "triangular_arbitrage"),
            exploration_ratio=0.35,
        ),
        GoalTier(
            level=3,
            threshold_usd=1_000_000.0,
            label="Elite",
            strategies=("cross_momentum", "stat_arb", "triangular_arbitrage"),
            exploration_ratio=0.40,
            whale_follow_size_mult=1.25,
        ),
    )


def _manager(tmp_path: Path, *, enabled: bool = True) -> GoalEvolutionManager:
    goal_cfg = GoalEvolutionConfig(
        enabled=enabled,
        state_file=tmp_path / ".tradebot_goals_state.json",
        tiers=_tiers(),
        base_exploration_ratio=0.25,
    )
    crash_cfg = CrashGuardConfig(
        enabled=True,
        drawdown_pct=0.08,
        session_drawdown_pct=0.06,
        recovery_drawdown_pct=0.05,
        momentum_threshold=-0.015,
        momentum_asset_ratio=0.60,
        watchdog_drawdown_pct=0.10,
        min_hold_minutes=30.0,
    )
    return GoalEvolutionManager(goal_cfg, crash_cfg)


def test_tier0_baseline_strategies(tmp_path):
    mgr = _manager(tmp_path)
    status = mgr.evaluate_goals(3_500.0)
    assert status.tier == 0
    assert status.allowed_strategies == ("cross_momentum",)
    assert status.exploration_ratio == pytest.approx(0.25)


def test_tier1_unlocks_stat_arb_once(tmp_path):
    mgr = _manager(tmp_path)
    first = mgr.evaluate_goals(12_000.0)
    second = mgr.evaluate_goals(12_500.0)
    assert first.tier == 1
    assert "stat_arb" in first.allowed_strategies
    assert first.newly_achieved is True
    assert second.newly_achieved is False
    assert 1 in mgr.state.achieved_tiers


def test_tier3_whale_follow_multiplier(tmp_path):
    mgr = _manager(tmp_path)
    status = mgr.evaluate_goals(1_200_000.0)
    assert status.tier == 3
    assert status.whale_follow_size_mult == pytest.approx(1.25)
    assert status.exploration_ratio == pytest.approx(0.40)


def test_filter_configured_strategies_intersection(tmp_path):
    mgr = _manager(tmp_path)
    filtered = mgr.filter_configured_strategies(
        ("cross_momentum", "stat_arb", "triangular_arbitrage"),
        ("cross_momentum",),
    )
    assert filtered == ("cross_momentum",)


def test_crash_hold_blocks_new_risk_on_drawdown(tmp_path):
    mgr = _manager(tmp_path)
    status = mgr.evaluate_crash_guard(
        portfolio_usd=9_000.0,
        peak_drawdown_pct=0.09,
        asset_momentum={"ETH": -0.001},
        watchdog_drawdown_pct=0.09,
        risk_paused=False,
        trading_active=True,
    )
    assert status.active is True
    assert status.blocks_new_risk is True
    assert status.newly_activated is True
    assert "peak drawdown" in status.activate_message


def test_crash_hold_defers_to_risk_pause(tmp_path):
    mgr = _manager(tmp_path)
    status = mgr.evaluate_crash_guard(
        portfolio_usd=9_000.0,
        peak_drawdown_pct=0.20,
        asset_momentum={"ETH": -0.05},
        watchdog_drawdown_pct=0.20,
        risk_paused=True,
        trading_active=True,
    )
    assert status.blocks_new_risk is False


def test_crash_hold_recovery_after_cooldown(tmp_path):
    mgr = _manager(tmp_path)
    mgr.state.crash_hold_active = True
    mgr.state.crash_hold_since = (
        datetime.now(timezone.utc) - timedelta(minutes=45)
    ).isoformat()
    mgr.state.crash_hold_reason = "peak drawdown 9.0%"
    mgr.state.crash_hold_triggers = ["peak drawdown 9.0%"]
    status = mgr.evaluate_crash_guard(
        portfolio_usd=9_800.0,
        peak_drawdown_pct=0.04,
        asset_momentum={"ETH": 0.002, "BTC": 0.001},
        watchdog_drawdown_pct=0.04,
        risk_paused=False,
        trading_active=True,
    )
    assert status.active is False
    assert status.newly_released is True


@dataclass
class _FakeSettings:
    goal_evolution_enabled: bool = True
    goal_state_file: Path = Path(".tradebot_goals_state.json")
    goal_milestones_usd: tuple[float, ...] = (10_000.0, 100_000.0, 1_000_000.0)
    goal_tier0_strategies: tuple[str, ...] = ("cross_momentum",)
    goal_tier1_strategies: tuple[str, ...] = ("cross_momentum", "stat_arb")
    goal_tier2_strategies: tuple[str, ...] = (
        "cross_momentum",
        "stat_arb",
        "triangular_arbitrage",
    )
    goal_tier3_strategies: tuple[str, ...] = (
        "cross_momentum",
        "stat_arb",
        "triangular_arbitrage",
    )
    goal_tier2_exploration_ratio: float | None = 0.35
    goal_tier3_exploration_ratio: float | None = 0.40
    goal_tier3_whale_follow_size_mult: float = 1.25
    strategy_exploration_ratio: float = 0.25
    crash_hold_enabled: bool = True
    crash_hold_drawdown_pct: float = 0.08
    crash_hold_session_drawdown_pct: float = 0.06
    crash_hold_recovery_drawdown_pct: float = 0.05
    crash_hold_momentum_threshold: float = -0.015
    crash_hold_momentum_asset_ratio: float = 0.60
    crash_hold_watchdog_drawdown_pct: float = 0.10
    crash_hold_min_minutes: float = 30.0


def test_build_manager_from_settings(tmp_path):
    settings = _FakeSettings(goal_state_file=tmp_path / "goals.json")
    mgr = build_manager_from_settings(settings)
    assert mgr.config.enabled is True
    assert len(mgr.config.tiers) == 4


def test_compute_primary_goal_progress():
    pg = compute_primary_goal(
        portfolio_usd=1653.94,
        next_threshold_usd=10_000.0,
        next_tier_level=1,
        next_tier_label="Growth",
        unlock_summary="Stat-arb pairs",
    )
    assert pg["number"] == 1
    assert pg["headline"] == "Goal 1: $10,000 portfolio (Growth)"
    assert pg["progress_pct"] == pytest.approx(16.5, abs=0.1)
    assert pg["achieved"] is False
    assert pg["unlock_summary"] == "Stat-arb pairs"


def test_format_primary_goal_discord():
    from bot.goal_evolution import GoalStatus

    pg = compute_primary_goal(
        portfolio_usd=1653.94,
        next_threshold_usd=10_000.0,
        next_tier_level=1,
        next_tier_label="Growth",
        unlock_summary="Stat-arb pairs",
    )
    status = GoalStatus(
        enabled=True,
        tier=0,
        tier_label="Baseline",
        portfolio_usd=1653.94,
        next_threshold_usd=10_000.0,
        next_tier_label="Growth",
        allowed_strategies=("cross_momentum",),
        exploration_ratio=0.25,
        whale_follow_size_mult=1.0,
        unlocked_capabilities=("Core momentum only",),
        newly_achieved=False,
        achievement_message="",
        primary_goal=pg,
    )
    line = format_primary_goal_discord(status)
    assert "Goal 1" in line
    assert "16.5%" in line
    assert "Stat-arb pairs" in line


def test_tier1_achievement_message_uses_goal_number(tmp_path):
    mgr = _manager(tmp_path)
    status = mgr.evaluate_goals(12_000.0)
    assert "Goal 1 reached" in status.achievement_message
