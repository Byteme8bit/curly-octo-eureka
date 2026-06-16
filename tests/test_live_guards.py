"""Tests for live route safety gates."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bot.live_broker import LiveBroker
from bot.live_guards import LIVE_CONFIRM_PHRASE, check_live_route, is_live_armed
from bot.markets import PairInfo, RouteLeg, TradeRoute
from bot.strategies.base import Signal
from bot.verifier.live_tag import build_live_verify_tag
from bot.verifier.models import Verdict
from config import load_settings


def _leg(base: str, quote: str, side: Signal = Signal.BUY) -> RouteLeg:
    symbol = f"{base}/{quote}"
    return RouteLeg(
        pair=PairInfo(symbol=symbol, base=base, quote=quote),
        side=side,
        from_asset=quote if side == Signal.BUY else base,
        to_asset=base if side == Signal.BUY else quote,
    )


def _route(*legs: RouteLeg) -> TradeRoute:
    return TradeRoute(legs=legs)


def test_single_hop_usd_allowed_by_default() -> None:
    route = _route(_leg("ETH", "USD", Signal.SELL))
    ok, reason = check_live_route(route, ("ETH", "ADA"))
    assert ok, reason


def test_single_hop_cross_blocked_without_triangular() -> None:
    route = _route(_leg("ADA", "ETH", Signal.BUY))
    ok, reason = check_live_route(route, ("ETH", "ADA"))
    assert not ok
    assert "*/USD" in reason


def test_multi_hop_blocked_without_triangular() -> None:
    route = _route(
        _leg("ETH", "USD", Signal.SELL),
        _leg("ADA", "USD", Signal.BUY),
        _leg("ETH", "USD", Signal.BUY),
    )
    ok, reason = check_live_route(route, ("ETH", "ADA"))
    assert not ok
    assert (
        "multi-hop" in reason.lower()
        or "LIVE_ALLOW_TRIANGULAR" in reason
        or "LIVE_MAX_ROUTE_LEGS" in reason
    )


def test_triangular_eth_ada_usd_loop_allowed() -> None:
    route = _route(
        _leg("ETH", "USD", Signal.SELL),
        _leg("ADA", "USD", Signal.BUY),
        _leg("ETH", "USD", Signal.BUY),
    )
    ok, reason = check_live_route(
        route,
        ("ETH", "ADA"),
        allow_triangular=True,
        max_route_legs=3,
    )
    assert ok, reason


def test_triangular_btc_bridge_allowed() -> None:
    route = _route(
        _leg("ETH", "BTC", Signal.SELL),
        _leg("ADA", "BTC", Signal.BUY),
    )
    ok, reason = check_live_route(
        route,
        ("ETH", "ADA"),
        allow_triangular=True,
        max_route_legs=3,
    )
    assert ok, reason


def test_triangular_rejects_unlisted_asset() -> None:
    route = _route(
        _leg("ETH", "UNI", Signal.SELL),
        _leg("UNI", "AAVE", Signal.BUY),
        _leg("ETH", "AAVE", Signal.BUY),
    )
    ok, reason = check_live_route(
        route,
        ("ETH", "ADA"),
        allow_triangular=True,
        max_route_legs=3,
    )
    assert not ok
    assert "UNI" in reason or "AAVE" in reason


def test_four_leg_triangular_route_allowed() -> None:
    route = _route(
        _leg("ETH", "UNI", Signal.SELL),
        _leg("UNI", "DOT", Signal.BUY),
        _leg("DOT", "USD", Signal.SELL),
        _leg("DOT", "ETH", Signal.SELL),
    )
    ok, reason = check_live_route(
        route,
        ("ETH", "DOT", "UNI", "AAVE", "SOL", "LINK", "XRP"),
        allow_triangular=True,
        max_route_legs=4,
    )
    assert ok, reason


def test_max_route_legs_cap() -> None:
    route = _route(
        _leg("ETH", "USD", Signal.SELL),
        _leg("ADA", "USD", Signal.BUY),
        _leg("ETH", "USD", Signal.BUY),
    )
    ok, reason = check_live_route(
        route,
        ("ETH", "ADA"),
        allow_triangular=True,
        max_route_legs=2,
    )
    assert not ok
    assert "LIVE_MAX_ROUTE_LEGS" in reason


def test_is_live_armed_requires_confirm_phrase() -> None:
    assert is_live_armed(live_enabled=True, live_trading_confirm=LIVE_CONFIRM_PHRASE)
    assert not is_live_armed(live_enabled=True, live_trading_confirm="")


def test_engine_rejects_live_without_confirm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVE_ENABLED", "1")
    monkeypatch.setenv("LIVE_TRADING_CONFIRM", "")
    monkeypatch.setenv("KRAKEN_API_KEY", "test-key")
    monkeypatch.setenv("KRAKEN_API_SECRET", "test-secret")
    from bot.engine import TradingEngine

    settings = load_settings()
    with pytest.raises(ValueError, match="LIVE_TRADING_CONFIRM"):
        TradingEngine(settings, MagicMock())


def test_live_tag_confirms_real_fill() -> None:
    trade = {
        "live": True,
        "order_id": "OX7B5B-LROFK-CFJ6BU",
        "symbol": "ETH/USD",
        "hops": 1,
    }
    result = build_live_verify_tag(trade, skip_kraken=True)
    assert result.verdict == Verdict.CONFIRM
    assert "Live fill confirmed" in result.tag


class _StubExchange:
    def fetch_balance(self):
        return {"total": {"ETH": 1.0, "ADA": 100.0, "USD": 50.0}}

    def market(self, symbol: str):
        return {"limits": {"amount": {"min": 0.0001}}}

    def amount_to_precision(self, symbol: str, amount: float) -> str:
        return f"{amount:.6f}"

    def create_order(self, symbol, order_type, side, amount):
        raise AssertionError("create_order should not run for blocked route")

    def fetch_order(self, order_id, symbol):
        return {}


def test_live_broker_blocks_triangular_execute_path(tmp_path: Path) -> None:
    broker = LiveBroker(
        exchange=_StubExchange(),
        fee_rate=0.0026,
        state_file=tmp_path / "live.json",
        min_usd_trade=5.0,
        max_usd_per_trade=100.0,
        allowed_assets=("ETH", "ADA"),
        allow_triangular=False,
        max_route_legs=1,
    )
    route = _route(
        _leg("ADA", "USD", Signal.BUY),
        _leg("ADA", "ETH", Signal.SELL),
        _leg("ETH", "USD", Signal.SELL),
    )
    result = broker.execute_path(
        route,
        prices={"ADA/USD": 0.5, "ADA/ETH": 0.0002, "ETH/USD": 3000.0},
        usd_prices={"ETH": 3000.0, "ADA": 0.5, "USD": 1.0},
        reason="triangular test",
    )
    assert result is None
