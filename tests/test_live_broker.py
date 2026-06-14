"""Tests for LiveBroker with a stub exchange."""

from __future__ import annotations

from pathlib import Path

import pytest
import ccxt

from bot.live_broker import LiveBroker
from bot.markets import PairInfo, RouteLeg, TradeRoute
from bot.strategies.base import Signal


class _StubExchange:
    def __init__(self) -> None:
        self.balances = {"ETH": 1.0, "USD": 5000.0, "ADA": 0.0}
        self.orders: list[dict] = []
        self.fail_after_orders = 0

    def fetch_balance(self):
        return {"total": dict(self.balances)}

    def market(self, symbol: str):
        return {"limits": {"amount": {"min": 0.0001}}}

    def amount_to_precision(self, symbol: str, amount: float) -> str:
        return f"{amount:.6f}"

    def create_order(self, symbol, order_type, side, amount):
        if self.fail_after_orders and len(self.orders) >= self.fail_after_orders:
            raise ccxt.ExchangeError("simulated exchange failure")
        base, quote = symbol.split("/")
        price = {"ETH/USD": 3000.0, "ADA/USD": 0.5, "ADA/ETH": 0.0002}.get(symbol, 1.0)
        order = {
            "id": f"oid-{len(self.orders)}",
            "symbol": symbol,
            "status": "closed",
            "filled": float(amount),
            "average": price,
            "fee": {"cost": float(amount) * price * 0.0026, "currency": quote},
            "fees": [],
        }
        if side == "sell":
            self.balances[base] = self.balances.get(base, 0) - float(amount)
            self.balances[quote] = self.balances.get(quote, 0) + float(amount) * price
        else:
            spend = float(amount) * price
            self.balances[quote] = self.balances.get(quote, 0) - spend
            self.balances[base] = self.balances.get(base, 0) + float(amount)
        self.orders.append(order)
        return order

    def fetch_order(self, order_id, symbol):
        return self.orders[-1]


@pytest.fixture
def live_broker(tmp_path: Path) -> LiveBroker:
    ex = _StubExchange()
    broker = LiveBroker(
        exchange=ex,
        fee_rate=0.0026,
        state_file=tmp_path / "live.json",
        min_usd_trade=10.0,
        max_usd_per_trade=500.0,
    )
    return broker


def test_live_sell_leg(live_broker: LiveBroker) -> None:
    pair = PairInfo(symbol="ETH/USD", base="ETH", quote="USD")
    trade = live_broker.execute(
        pair,
        Signal.SELL,
        price=3000.0,
        usd_prices={"ETH": 3000.0},
        reason="test sell",
        size_pct=0.1,
    )
    assert trade is not None
    assert trade["live"] is True
    assert trade.get("order_id")
    assert live_broker.balance("ETH") < 1.0


def test_record_completed_trade_persists(live_broker: LiveBroker) -> None:
    assert live_broker.risk.live_trades_completed == 0
    assert live_broker.record_completed_trade() == 1
    assert live_broker.risk.live_trades_completed == 1
    reloaded = LiveBroker(
        exchange=live_broker.exchange,
        fee_rate=live_broker.fee_rate,
        state_file=live_broker.state_file,
    )
    assert reloaded.risk.live_trades_completed == 1


def test_live_halt_blocks_execution(live_broker: LiveBroker) -> None:
    live_broker.halt("test halt")
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
    result = live_broker.execute_path(
        route,
        prices={"ETH/USD": 3000.0},
        usd_prices={"ETH": 3000.0},
        reason="blocked",
    )
    assert result is None


def test_triangular_path_sequential_execution(tmp_path: Path) -> None:
    ex = _StubExchange()
    broker = LiveBroker(
        exchange=ex,
        fee_rate=0.0026,
        state_file=tmp_path / "live.json",
        min_usd_trade=10.0,
        max_usd_per_trade=500.0,
        max_usd_per_route=500.0,
        allow_triangular=True,
        max_route_legs=3,
    )
    route = TradeRoute(
        legs=(
            RouteLeg(
                pair=PairInfo(symbol="ETH/USD", base="ETH", quote="USD"),
                side=Signal.SELL,
                from_asset="ETH",
                to_asset="USD",
            ),
            RouteLeg(
                pair=PairInfo(symbol="ADA/USD", base="ADA", quote="USD"),
                side=Signal.BUY,
                from_asset="USD",
                to_asset="ADA",
            ),
        )
    )
    eth_before = broker.balance("ETH")
    trade = broker.execute_path(
        route,
        prices={"ETH/USD": 3000.0, "ADA/USD": 0.5},
        usd_prices={"ETH": 3000.0, "ADA": 0.5},
        reason="triangular test",
        size_pct=0.1,
        strategy_name="triangular_arbitrage",
    )
    assert trade is not None
    assert trade["hops"] == 2
    assert trade["live"] is True
    assert broker.balance("ETH") < eth_before
    assert broker.balance("ADA") > 0


def test_mid_route_failure_halts_and_attempts_rollback(tmp_path: Path) -> None:
    ex = _StubExchange()
    broker = LiveBroker(
        exchange=ex,
        fee_rate=0.0026,
        state_file=tmp_path / "live.json",
        min_usd_trade=10.0,
        max_usd_per_trade=500.0,
        max_usd_per_route=500.0,
        allow_triangular=True,
        max_route_legs=3,
    )
    route = TradeRoute(
        legs=(
            RouteLeg(
                pair=PairInfo(symbol="ETH/USD", base="ETH", quote="USD"),
                side=Signal.SELL,
                from_asset="ETH",
                to_asset="USD",
            ),
            RouteLeg(
                pair=PairInfo(symbol="ADA/USD", base="ADA", quote="USD"),
                side=Signal.BUY,
                from_asset="USD",
                to_asset="ADA",
            ),
        )
    )
    ex.fail_after_orders = 1
    result = broker.execute_path(
        route,
        prices={"ETH/USD": 3000.0, "ADA/USD": 0.5},
        usd_prices={"ETH": 3000.0, "ADA": 0.5},
        reason="fail leg 2",
        size_pct=0.1,
    )
    assert result is None
    assert broker.halted
    assert "leg 2" in broker.halt_reason.lower() or "failed" in broker.halt_reason.lower()


def test_multi_hop_blocked_when_triangular_disabled(tmp_path: Path) -> None:
    ex = _StubExchange()
    broker = LiveBroker(
        exchange=ex,
        fee_rate=0.0026,
        state_file=tmp_path / "live.json",
        min_usd_trade=10.0,
        max_usd_per_trade=500.0,
        allow_triangular=False,
    )
    route = TradeRoute(
        legs=(
            RouteLeg(
                pair=PairInfo(symbol="ETH/USD", base="ETH", quote="USD"),
                side=Signal.SELL,
                from_asset="ETH",
                to_asset="USD",
            ),
            RouteLeg(
                pair=PairInfo(symbol="ADA/USD", base="ADA", quote="USD"),
                side=Signal.BUY,
                from_asset="USD",
                to_asset="ADA",
            ),
        )
    )
    assert broker.execute_path(
        route,
        prices={"ETH/USD": 3000.0, "ADA/USD": 0.5},
        usd_prices={"ETH": 3000.0, "ADA": 0.5},
        reason="blocked",
    ) is None
