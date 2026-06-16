"""Live route balance preflight — block before placing orders."""

from __future__ import annotations

from pathlib import Path

import ccxt
import pytest

from bot.live_broker import LiveBroker
from bot.markets import PairInfo, RouteLeg, TradeRoute
from bot.strategies.base import Signal


class _StubExchange:
    def __init__(self) -> None:
        self.balances = {"ETH": 1.0, "USD": 500.0, "UNI": 0.0, "BTC": 0.0}
        self.orders: list[dict] = []

    def fetch_balance(self):
        return {"total": dict(self.balances)}

    def market(self, symbol: str):
        return {"limits": {"amount": {"min": 0.0001}}}

    def amount_to_precision(self, symbol: str, amount: float) -> str:
        return f"{amount:.6f}"

    def create_order(self, symbol, order_type, side, amount):
        base, quote = symbol.split("/")
        prices = {
            "UNI/ETH": 0.0016,
            "UNI/BTC": 4.325e-05,
            "ETH/BTC": 0.0269,
        }
        price = prices.get(symbol, 1.0)
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


def test_preflight_blocks_when_leg2_lacks_intermediate_asset(tmp_path: Path) -> None:
    """Leg 2 needs UNI from leg 1 — preflight fails without placing orders."""
    ex = _StubExchange()
    ex.balances["UNI"] = 0.0
    broker = LiveBroker(
        exchange=ex,
        fee_rate=0.0026,
        state_file=tmp_path / "live.json",
        min_usd_trade=10.0,
        max_usd_per_trade=500.0,
        max_usd_per_route=500.0,
        allowed_assets=("ETH", "BTC", "UNI"),
        allow_triangular=True,
        max_route_legs=3,
    )
    route = TradeRoute(
        legs=(
            RouteLeg(
                pair=PairInfo("UNI/ETH", "UNI", "ETH"),
                side=Signal.BUY,
                from_asset="ETH",
                to_asset="UNI",
            ),
            RouteLeg(
                pair=PairInfo("UNI/BTC", "UNI", "BTC"),
                side=Signal.SELL,
                from_asset="UNI",
                to_asset="BTC",
            ),
        )
    )
    prices = {"UNI/ETH": 0.0016, "UNI/BTC": 4.325e-05}
    ok, reason = broker._preflight_route(
        route, prices, {"ETH": 3000.0, "UNI": 3.0, "BTC": 65000.0}, 0.05
    )
    assert ok is True  # leg 1 produces UNI for leg 2
    assert reason == ""

    # Wallet has UNI but route simulation still chains correctly
    ex.balances["UNI"] = 100.0  # stale wallet UNI must not break preflight
    ok2, _ = broker._preflight_route(
        route, prices, {"ETH": 3000.0, "UNI": 3.0, "BTC": 65000.0}, 0.05
    )
    assert ok2 is True


def test_execute_path_preflight_failure_does_not_halt(tmp_path: Path) -> None:
    ex = _StubExchange()
    ex.balances = {"ETH": 0.001, "USD": 0.0}  # too small for min trade
    broker = LiveBroker(
        exchange=ex,
        fee_rate=0.0026,
        state_file=tmp_path / "live.json",
        min_usd_trade=10.0,
        max_usd_per_trade=500.0,
        allow_triangular=True,
        max_route_legs=3,
    )
    route = TradeRoute(
        legs=(
            RouteLeg(
                pair=PairInfo("ETH/USD", "ETH", "USD"),
                side=Signal.SELL,
                from_asset="ETH",
                to_asset="USD",
            ),
            RouteLeg(
                pair=PairInfo("ADA/USD", "ADA", "USD"),
                side=Signal.BUY,
                from_asset="USD",
                to_asset="ADA",
            ),
        )
    )
    result = broker.execute_path(
        route,
        prices={"ETH/USD": 3000.0, "ADA/USD": 0.5},
        usd_prices={"ETH": 3000.0, "ADA": 0.5},
        reason="preflight block",
        size_pct=0.1,
    )
    assert result is None
    assert not broker.halted
    assert len(ex.orders) == 0
