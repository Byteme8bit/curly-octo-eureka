"""Tests for 50/50 crypto/equity bucket allocation (feature 070)."""

from __future__ import annotations

import pytest

from bot.portfolio_constraints import PortfolioConstraints
from bot.strategies.base import TradeIntent

EQUITY_ASSETS = frozenset({"AAPLx", "SPYx"})


@pytest.fixture
def constraints() -> PortfolioConstraints:
    return PortfolioConstraints(
        min_eth_reserve=0.25,
        max_alt_allocation_pct=0.40,
        min_usd_trade=10.0,
        equity_assets=EQUITY_ASSETS,
        max_equity_allocation_pct=0.25,
        target_equity_allocation_pct=0.50,
        target_crypto_allocation_pct=0.50,
        max_equity_bucket_pct=0.55,
        max_crypto_bucket_pct=0.55,
        equity_accumulation_phase=True,
        equity_dca_priority=True,
        equity_accumulation_min_pct=0.45,
    )


@pytest.fixture
def prices() -> dict[str, float]:
    return {
        "USD": 1.0,
        "ETH": 2000.0,
        "SOL": 100.0,
        "AAPLx": 200.0,
        "SPYx": 500.0,
    }


def test_bucket_allocation_math(constraints, prices):
    # crypto $700 + equity $300 + USD $100 = $1100
    holdings = {"ETH": 0.35, "USD": 100.0, "AAPLx": 1.0, "SPYx": 0.2}
    buckets = constraints.bucket_allocation(holdings, prices)
    assert buckets.portfolio_usd == pytest.approx(1100.0)
    assert buckets.crypto_pct == pytest.approx(700.0 / 1100.0, rel=1e-3)
    assert buckets.equity_pct == pytest.approx(300.0 / 1100.0, rel=1e-3)
    assert buckets.usd_pct == pytest.approx(100.0 / 1100.0, rel=1e-3)


def test_in_equity_accumulation_when_underweight(constraints, prices):
    holdings = {"ETH": 1.0, "USD": 500.0, "AAPLx": 0.5}
    assert constraints.in_equity_accumulation(holdings, prices)


def test_blocks_equity_to_crypto_during_accumulation(constraints, prices):
    holdings = {"USD": 50.0, "AAPLx": 2.0, "ETH": 0.5}
    intent = TradeIntent(
        from_asset="AAPLx",
        to_asset="ETH",
        reason="rotation",
        size_pct=0.25,
        edge=0.01,
        strategy_name="cross_momentum",
    )
    result = constraints.validate_intent(intent, holdings, prices, required_edge=0.005)
    assert not result.allowed
    assert "Equity accumulation" in result.reason


def test_allows_equity_to_crypto_when_severely_overweight(constraints, prices):
    holdings = {"USD": 50.0, "AAPLx": 20.0, "SPYx": 10.0, "ETH": 0.1}
    intent = TradeIntent(
        from_asset="AAPLx",
        to_asset="ETH",
        reason="rotation",
        size_pct=0.10,
        edge=0.01,
        strategy_name="cross_momentum",
    )
    result = constraints.validate_intent(intent, holdings, prices, required_edge=0.005)
    assert result.allowed, result.reason


def test_trim_crypto_bucket_sells_alt_to_usd(constraints, prices):
    # crypto ~73%, equity ~18%
    holdings = {"ETH": 0.5, "SOL": 5.0, "USD": 100.0, "AAPLx": 1.0}
    def has_path(a, b):
        return (a, b) in {
            ("SOL", "USD"),
            ("ETH", "USD"),
            ("AAPLx", "USD"),
        }

    intents = constraints.trim_overweight_intents(holdings, prices, has_path)
    assert intents
    assert intents[0].to_asset == "USD"
    assert intents[0].is_defensive
    assert "crypto bucket" in intents[0].reason.lower()


def test_format_allocation_line(constraints, prices):
    holdings = {"ETH": 0.5, "USD": 200.0, "AAPLx": 1.0}
    line = constraints.format_allocation_line(holdings, prices)
    assert "crypto" in line.lower()
    assert "equity" in line.lower()
    assert "50%" in line or "50.0%" in line
