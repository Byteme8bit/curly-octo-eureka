"""Tests for ETH-floor + alt-allocation cap (feature 001)."""
from __future__ import annotations

import pytest

from bot.portfolio_constraints import PortfolioConstraints
from bot.strategies.base import TradeIntent


@pytest.fixture
def constraints() -> PortfolioConstraints:
    return PortfolioConstraints(
        min_eth_reserve=0.25,
        max_alt_allocation_pct=0.40,
        min_usd_trade=10.0,
    )


@pytest.fixture
def prices() -> dict[str, float]:
    return {"ETH": 2000.0, "BTC": 50000.0, "ADA": 0.50, "SOL": 100.0}


def test_eth_sell_clamped_to_reserve(constraints):
    holdings = {"ETH": 0.5, "ADA": 0.0, "USD": 0.0}
    clamped = constraints.clamp_eth_sell_size("ETH", size_pct=1.0, holdings=holdings)
    # Can only sell 0.25 of 0.5 ETH = 50%
    assert clamped == pytest.approx(0.5, rel=1e-6)


def test_eth_sell_blocked_at_floor(constraints):
    holdings = {"ETH": 0.25, "USD": 0.0}
    clamped = constraints.clamp_eth_sell_size("ETH", size_pct=0.5, holdings=holdings)
    assert clamped == 0.0


def test_eth_sell_unrestricted_above_floor(constraints):
    holdings = {"ETH": 2.0, "USD": 0.0}
    clamped = constraints.clamp_eth_sell_size("ETH", size_pct=0.10, holdings=holdings)
    assert clamped == 0.10


def test_non_eth_sell_not_clamped(constraints):
    holdings = {"ADA": 100.0, "USD": 0.0}
    clamped = constraints.clamp_eth_sell_size("ADA", size_pct=0.50, holdings=holdings)
    assert clamped == 0.50


def test_alt_overweight_blocked_without_strategy(constraints, prices):
    # ETH 1.0 = $2000, ADA already $1500 (43%) of $3500 total, want to buy more ADA
    holdings = {"ETH": 1.0, "ADA": 3000.0, "USD": 0.0}
    intent = TradeIntent(
        from_asset="ETH",
        to_asset="ADA",
        reason="diversify",
        size_pct=0.50,
        edge=0.001,
        strategy_name="momentum_rotation",
    )
    result = constraints.validate_intent(intent, holdings, prices, required_edge=0.005)
    assert not result.allowed
    assert "Alt cap" in result.reason


def test_eth_to_btc_always_allowed(constraints, prices):
    holdings = {"ETH": 5.0, "USD": 0.0}
    intent = TradeIntent(
        from_asset="ETH",
        to_asset="BTC",
        reason="rotation",
        size_pct=0.50,
        edge=0.001,
        strategy_name="cross_momentum",
    )
    result = constraints.validate_intent(intent, holdings, prices, required_edge=0.005)
    assert result.allowed


def test_alt_overweight_allowed_with_stat_arb_exception(constraints, prices):
    # ADA currently $750 / $2750 = 27% (under cap). Trade pushes projected over cap.
    holdings = {"ETH": 1.0, "ADA": 1500.0, "USD": 0.0}
    intent = TradeIntent(
        from_asset="ETH",
        to_asset="ADA",
        reason="stat arb pair convergence",
        size_pct=0.50,
        edge=0.01,
        gross_return_pct=0.01,
        strategy_name="stat_arb",
    )
    result = constraints.validate_intent(intent, holdings, prices, required_edge=0.005)
    assert result.allowed, result.reason


def test_closed_loop_eth_exempted_from_reserve_check(constraints):
    """ETH→X→Y→ETH closed loop: ETH is only an intermediate; reserve must NOT block it."""
    # ETH balance equals the reserve — an open sell would be blocked, but a closed loop
    # returns ETH atomically so the net holding is unchanged.
    holdings = {"ETH": 0.25, "USD": 0.0}
    prices = {"ETH": 2000.0}
    intent = TradeIntent(
        from_asset="ETH",
        to_asset="ETH",  # closed loop
        reason="triangular arb loop ETH->UNI->AAVE->ETH",
        size_pct=0.10,
        edge=0.005,
        strategy_name="triangular_arbitrage",
    )
    result = constraints.validate_intent(intent, holdings, prices, required_edge=0.002)
    assert result.allowed, f"closed-loop should bypass reserve check; got: {result.reason}"


def test_open_eth_sell_still_blocked_at_reserve(constraints):
    """Open ETH sell (from_asset=ETH, to_asset≠ETH) is still blocked at the reserve floor."""
    holdings = {"ETH": 0.25, "USD": 0.0}
    prices = {"ETH": 2000.0, "UNI": 10.0}
    intent = TradeIntent(
        from_asset="ETH",
        to_asset="UNI",  # open sell — NOT a closed loop
        reason="momentum swap",
        size_pct=0.10,
        edge=0.005,
        strategy_name="momentum_rotation",
    )
    result = constraints.validate_intent(intent, holdings, prices, required_edge=0.002)
    assert not result.allowed, "open ETH sell at reserve floor must still be blocked"
    assert "ETH reserve" in result.reason


def test_trim_overweight_alt_emits_intent(constraints, prices):
    # ADA = $4000 / $6000 total = 67% > 40% cap
    holdings = {"ETH": 1.0, "ADA": 8000.0, "USD": 0.0}
    def has_path(a, b):
        return True
    intents = constraints.trim_overweight_intents(holdings, prices, has_path)
    assert len(intents) == 1
    assert intents[0].from_asset == "ADA"
    assert intents[0].to_asset == "ETH"
    assert intents[0].is_defensive
