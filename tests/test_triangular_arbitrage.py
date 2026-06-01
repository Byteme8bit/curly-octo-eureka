"""Tests for triangular-arb loop closure (feature 030).

Regression guard for the fee-bleed bug where the scanner emitted only leg 1 of
an A->B->C->A loop, accumulating an intermediate coin and paying a fee with no
compensating legs. The fix emits the WHOLE loop as one atomic route so it either
completes (start asset == end asset) or does not fire.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.markets import PairInfo, RouteLeg, TradeRoute
from bot.paper_broker import PaperBroker
from bot.strategies.base import Signal, StrategyContext
from bot.strategies.triangular_arbitrage import TriangularArbitrageStrategy


# A=ETH, B=UNI, C=AAVE. Each leg is a BUY of the base using the quote.
PAIRS = {
    ("ETH", "UNI"): PairInfo(symbol="UNI/ETH", base="UNI", quote="ETH"),
    ("UNI", "AAVE"): PairInfo(symbol="AAVE/UNI", base="AAVE", quote="UNI"),
    ("AAVE", "ETH"): PairInfo(symbol="ETH/AAVE", base="ETH", quote="AAVE"),
}


class FakeMarkets:
    """Minimal MarketRegistry stand-in returning single-leg BUY routes."""

    def find_path(self, from_asset: str, to_asset: str, max_hops: int = 3):
        pair = PAIRS.get((from_asset, to_asset))
        if not pair:
            return None
        leg = RouteLeg(
            pair=pair, side=Signal.BUY, from_asset=from_asset, to_asset=to_asset
        )
        return TradeRoute(legs=(leg,))


def _strategy(watch=("ETH", "UNI", "AAVE")):
    settings = SimpleNamespace(
        watch_assets=watch,
        trade_size_pct=0.10,
        fee_rate=0.004,
        min_net_profit_pct=0.001,
        dust_usd=25.0,
    )
    return TriangularArbitrageStrategy(settings)


def _profitable_prices():
    # product of the three BUY prices < 1 => the loop multiplies the start
    # amount. 0.9 * 0.9 * 0.9 = 0.729 => ~+37% pre-fee, well above any fee drag.
    return {"UNI/ETH": 0.9, "AAVE/UNI": 0.9, "ETH/AAVE": 0.9}


def _flat_prices():
    # product == 1 => a pure round-trip with no edge; must NOT fire.
    return {"UNI/ETH": 1.0, "AAVE/UNI": 1.0, "ETH/AAVE": 1.0}


def test_emits_closed_loop_intent_with_full_route():
    strat = _strategy()
    ctx = StrategyContext(pair_prices=_profitable_prices())
    result = strat.evaluate(
        candles={}, prices={"ETH": 2000.0, "UNI": 10.0, "AAVE": 100.0},
        holdings={"ETH": 1.0}, risk=None, markets=FakeMarkets(), context=ctx,
    )
    assert result.intents, "a profitable loop should emit an intent"
    intent = result.intents[0]
    # The intent is a CLOSED loop: start asset == end asset.
    assert intent.from_asset == intent.to_asset == "ETH"
    # It carries a pre-built 3-leg route covering the whole loop.
    assert intent.route is not None
    assert intent.route.hops == 3
    assert intent.route.legs[0].from_asset == "ETH"
    assert intent.route.legs[-1].to_asset == "ETH"
    # gross_return_pct is PRE-fee (so pre-flight can subtract real fees).
    assert intent.gross_return_pct > intent.edge


def test_flat_loop_does_not_fire():
    strat = _strategy()
    ctx = StrategyContext(pair_prices=_flat_prices())
    result = strat.evaluate(
        candles={}, prices={"ETH": 2000.0, "UNI": 10.0, "AAVE": 100.0},
        holdings={"ETH": 1.0}, risk=None, markets=FakeMarkets(), context=ctx,
    )
    assert not result.intents, "a no-edge round trip must not churn fees"


def test_route_executes_atomically_and_returns_to_start():
    """The whole loop runs in one shot: we end holding ETH, not the intermediate."""
    strat = _strategy()
    ctx = StrategyContext(pair_prices=_profitable_prices())
    result = strat.evaluate(
        candles={}, prices={"ETH": 2000.0, "UNI": 10.0, "AAVE": 100.0},
        holdings={"ETH": 1.0}, risk=None, markets=FakeMarkets(), context=ctx,
    )
    intent = result.intents[0]

    with tempfile.TemporaryDirectory() as tmp:
        broker = PaperBroker(
            initial_balances={"ETH": 1.0},
            fee_rate=0.004,
            state_file=Path(tmp) / "state.json",
            min_usd_trade=1.0,
            reset=True,
        )
        usd_prices = {"ETH": 2000.0, "UNI": 10.0, "AAVE": 100.0}
        prices = _profitable_prices()
        trade = broker.execute_path(
            route=intent.route,
            prices=prices,
            usd_prices=usd_prices,
            reason=intent.reason,
            size_pct=1.0,
            strategy_name=intent.strategy_name,
        )
        assert trade is not None
        assert trade["hops"] == 3
        # Start asset == end asset; intermediates fully consumed (no stranded coin).
        assert broker.balance("UNI") == pytest.approx(0.0, abs=1e-9)
        assert broker.balance("AAVE") == pytest.approx(0.0, abs=1e-9)
        # The profitable synthetic loop leaves us with MORE ETH than we started.
        assert broker.balance("ETH") > 1.0
