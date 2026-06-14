"""Tests for live 0.5 ETH hard floor (feature 051)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from bot.engine import TradingEngine
from bot.markets import PairInfo, RouteLeg, TradeRoute
from bot.portfolio_constraints import PortfolioConstraints
from bot.strategies.base import Signal, TradeIntent
from config import load_settings


@pytest.fixture
def live_constraints() -> PortfolioConstraints:
    return PortfolioConstraints(
        min_eth_reserve=0.5,
        max_alt_allocation_pct=0.40,
        min_usd_trade=10.0,
        strict_eth_floor=True,
    )


@pytest.fixture
def paper_constraints() -> PortfolioConstraints:
    return PortfolioConstraints(
        min_eth_reserve=0.25,
        max_alt_allocation_pct=0.40,
        min_usd_trade=10.0,
        strict_eth_floor=False,
    )


def test_config_live_min_eth_reserve_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LIVE_MIN_ETH_RESERVE", raising=False)
    monkeypatch.setenv("LIVE_ENABLED", "1")
    settings = load_settings()
    assert settings.live_min_eth_reserve == pytest.approx(0.5)


def test_strict_closed_loop_eth_clamped(live_constraints: PortfolioConstraints) -> None:
    holdings = {"ETH": 0.55, "USD": 0.0}
    prices = {"ETH": 3000.0, "UNI": 10.0, "AAVE": 100.0}
    intent = TradeIntent(
        from_asset="ETH",
        to_asset="ETH",
        reason="triangular arb loop ETH->UNI->AAVE->ETH",
        size_pct=0.20,
        edge=0.005,
        strategy_name="triangular_arbitrage",
    )
    result = live_constraints.validate_intent(intent, holdings, prices, required_edge=0.002)
    assert result.allowed, result.reason
    assert result.size_pct == pytest.approx(0.0909, rel=0.01)


def test_strict_closed_loop_eth_blocked_at_floor(live_constraints: PortfolioConstraints) -> None:
    holdings = {"ETH": 0.5, "USD": 0.0}
    prices = {"ETH": 3000.0}
    intent = TradeIntent(
        from_asset="ETH",
        to_asset="ETH",
        reason="triangular arb loop",
        size_pct=0.10,
        edge=0.005,
        strategy_name="triangular_arbitrage",
    )
    result = live_constraints.validate_intent(intent, holdings, prices, required_edge=0.002)
    assert not result.allowed
    assert "ETH reserve" in result.reason


def test_paper_closed_loop_still_exempted(paper_constraints: PortfolioConstraints) -> None:
    holdings = {"ETH": 0.25, "USD": 0.0}
    prices = {"ETH": 2000.0}
    intent = TradeIntent(
        from_asset="ETH",
        to_asset="ETH",
        reason="triangular arb loop",
        size_pct=0.10,
        edge=0.005,
        strategy_name="triangular_arbitrage",
    )
    result = paper_constraints.validate_intent(intent, holdings, prices, required_edge=0.002)
    assert result.allowed, result.reason


def test_route_eth_floor_blocks_cross_sell(live_constraints: PortfolioConstraints) -> None:
    pair = PairInfo(symbol="ETH/USD", base="ETH", quote="USD")
    route = TradeRoute(
        legs=(
            RouteLeg(
                pair=pair,
                side=Signal.SELL,
                from_asset="ETH",
                to_asset="USD",
            ),
        )
    )
    holdings = {"ETH": 0.55, "USD": 0.0}
    result = live_constraints.check_route_eth_floor(route, holdings, size_pct=0.20)
    assert not result.allowed
    assert "ETH reserve" in result.reason


def test_route_eth_floor_allows_trim_into_eth(live_constraints: PortfolioConstraints) -> None:
    pair = PairInfo(symbol="ADA/ETH", base="ADA", quote="ETH")
    route = TradeRoute(
        legs=(
            RouteLeg(
                pair=pair,
                side=Signal.SELL,
                from_asset="ADA",
                to_asset="ETH",
            ),
        )
    )
    holdings = {"ETH": 0.5, "ADA": 1000.0}
    result = live_constraints.check_route_eth_floor(route, holdings, size_pct=0.10)
    assert result.allowed, result.reason


def test_check_live_eth_floor_halts_broker() -> None:
    engine = TradingEngine.__new__(TradingEngine)
    engine._live_mode = True
    engine._mirror_mode = False
    engine.live_broker = None
    engine.settings = MagicMock(live_min_eth_reserve=0.5, discord_enabled=False)
    engine.runtime = MagicMock()
    engine.broker = MagicMock(halted=False)
    engine.discord = MagicMock()

    halted = engine._check_live_eth_floor({"ETH": 0.45, "USD": 0.0})

    assert halted is True
    engine.runtime.set_trading_active.assert_called_once_with(False)
    engine.broker.halt.assert_called_once()
    assert "0.5" in engine.broker.halt.call_args[0][0]


def test_check_live_eth_floor_mirror_halts_live_only() -> None:
    engine = TradingEngine.__new__(TradingEngine)
    engine._live_mode = True
    engine._mirror_mode = True
    engine.settings = MagicMock(live_min_eth_reserve=0.5, discord_enabled=False)
    engine.runtime = MagicMock()
    engine.live_broker = MagicMock(halted=False)
    engine.discord = MagicMock()

    halted = engine._check_live_eth_floor({"ETH": 0.45, "USD": 0.0})

    assert halted is True
    engine.runtime.set_trading_active.assert_not_called()
    engine.live_broker.halt.assert_called_once()


def test_try_execute_intent_blocks_eth_sell_below_floor() -> None:
    engine = TradingEngine.__new__(TradingEngine)
    engine._live_mode = True
    engine._mirror_mode = False
    engine.live_broker = None
    engine.settings = MagicMock(live_min_eth_reserve=0.5)
    engine.broker = MagicMock(halted=False)

    intent = TradeIntent(
        from_asset="ETH",
        to_asset="USD",
        reason="test sell",
        size_pct=0.50,
        edge=0.01,
    )
    trade, reason = engine._try_execute_intent(
        intent,
        holdings={"ETH": 0.45, "USD": 0.0},
        usd_prices={"ETH": 3000.0},
        portfolio=1350.0,
    )
    assert trade is None
    assert "below live floor" in reason
