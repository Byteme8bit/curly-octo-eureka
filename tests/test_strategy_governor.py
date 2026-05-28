"""Tests for strategy stickiness + exploration (feature 002)."""
from __future__ import annotations

from dataclasses import dataclass, field

from bot.strategies.base import TradeIntent
from bot.strategy_governor import StrategyGovernor


@dataclass
class _FakeRiskState:
    dominant_strategy: str | None = None
    dominant_since: str | None = None
    growth_window_start_at: str | None = None
    growth_window_start_value: float = 0.0
    strategy_stats: dict = field(default_factory=dict)
    total_trades: int = 0


def _build_governor(**overrides):
    state = _FakeRiskState()
    governor = StrategyGovernor(
        state,
        growth_window_hours=4.0,
        min_growth_pct=0.005,
        strong_growth_pct=0.015,
        switch_edge_margin=0.002,
        exploration_ratio=0.25,
        save_callback=lambda: None,
    )
    for key, value in overrides.items():
        setattr(state, key, value)
    return governor, state


def _intent(strategy: str, edge: float, **kwargs) -> TradeIntent:
    return TradeIntent(
        from_asset=kwargs.get("from_asset", "USD"),
        to_asset=kwargs.get("to_asset", "ETH"),
        reason=kwargs.get("reason", "test"),
        size_pct=0.10,
        edge=edge,
        gross_return_pct=edge,
        strategy_name=strategy,
    )


def test_no_dominant_strategy_passes_through():
    governor, _ = _build_governor()
    intents = [_intent("a", 0.01), _intent("b", 0.005)]
    out, status, notes = governor.apply(intents, adaptive=False)
    assert len(out) == 2
    assert status.dominant_strategy is None
    assert notes == []


def test_strong_growth_locks_dominant():
    governor, state = _build_governor(dominant_strategy="cross_momentum")
    state.growth_window_start_value = 1000.0
    governor.set_portfolio_snapshot(1020.0)  # +2% growth = strong

    challenger = _intent("stat_arb", 0.010)
    incumbent = _intent("cross_momentum", 0.008)
    out, status, notes = governor.apply([challenger, incumbent], adaptive=False)

    # Margin is 2x base when strong: 0.004. Challenger gap = 0.002 < margin -> stay
    assert out[0].strategy_name == "cross_momentum"
    assert status.lock_level == "strong"
    assert any("Stickiness" in n for n in notes)


def test_consistent_growth_allows_clear_winner():
    governor, state = _build_governor(dominant_strategy="cross_momentum")
    state.growth_window_start_value = 1000.0
    governor.set_portfolio_snapshot(1008.0)  # +0.8% = consistent

    challenger = _intent("stat_arb", 0.015)
    incumbent = _intent("cross_momentum", 0.008)
    out, status, notes = governor.apply([challenger, incumbent], adaptive=False)

    # Consistent margin = 0.002, gap 0.007 > margin -> switch allowed
    assert out[0].strategy_name == "stat_arb"
    assert any("switch allowed" in n.lower() for n in notes)


def test_record_trade_resets_growth_window_on_switch():
    governor, state = _build_governor(dominant_strategy="cross_momentum")
    state.growth_window_start_value = 1000.0
    governor.record_trade("stat_arb", portfolio_value=1020.0, gain_loss=5.0)
    assert state.dominant_strategy == "stat_arb"
    assert state.growth_window_start_value == 1020.0
    assert state.strategy_stats["stat_arb"]["trades"] == 1
    assert state.strategy_stats["stat_arb"]["pnl"] == 5.0
    assert state.strategy_stats["stat_arb"]["wins"] == 1


def test_record_trade_loss_does_not_increment_wins():
    governor, state = _build_governor()
    governor.record_trade("stat_arb", portfolio_value=1000.0, gain_loss=-3.0)
    assert state.strategy_stats["stat_arb"]["trades"] == 1
    assert state.strategy_stats["stat_arb"]["wins"] == 0
    assert state.strategy_stats["stat_arb"]["pnl"] == -3.0


def test_defensive_intents_always_kept_first():
    governor, _ = _build_governor()
    defensive = TradeIntent(
        from_asset="ADA",
        to_asset="ETH",
        reason="trim alt",
        size_pct=0.20,
        edge=0.0,
        is_defensive=True,
        strategy_name="portfolio_constraints",
    )
    offensive = _intent("stat_arb", 0.02)
    out, _, _ = governor.apply([offensive, defensive], adaptive=False)
    assert out[0].is_defensive
