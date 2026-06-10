"""Tests for whale-follow direction, cooldown, and gated execution."""

from __future__ import annotations

import time

import pandas as pd
import pytest

from bot.adaptive import fee_floor_edge
from bot.preflight import PreFlightValidator
from bot.fee_engine import FeeEngine
from bot.portfolio_constraints import PortfolioConstraints
from bot.strategies.base import TradeIntent
from bot.strategies.whale_follow import (
    WhaleFollowCooldown,
    WhaleFollowResult,
    build_whale_follow_reason,
    estimate_whale_follow_edge,
    evaluate_whale_follow,
    infer_spike_direction,
    infer_whale_direction,
    resolve_follow_route,
)
from bot.whale_watch import WhaleEvent


def _event(**kwargs) -> WhaleEvent:
    defaults = dict(
        id="e1",
        time="2026-06-09 12:00:00 PDT",
        asset="ETH",
        pair="ETH/USD",
        direction="buy",
        usd_size=80000,
        source="kraken_trade",
        detail="",
    )
    defaults.update(kwargs)
    return WhaleEvent(**defaults)


def _candles_with_spike(*, bullish: bool) -> pd.DataFrame:
    rows = []
    for i in range(14):
        rows.append({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 10.0})
    o, c = (100.0, 101.5) if bullish else (100.0, 98.5)
    rows.append({"open": o, "high": max(o, c), "low": min(o, c), "close": c, "volume": 50.0})
    return pd.DataFrame(rows)


def test_infer_spike_direction():
    assert infer_spike_direction(_candles_with_spike(bullish=True)) == "buy"
    assert infer_spike_direction(_candles_with_spike(bullish=False)) == "sell"
    flat = pd.DataFrame([{"open": 100, "close": 100.05, "volume": 1}] * 5)
    assert infer_spike_direction(flat) == "unknown"


def test_infer_whale_direction_trade_side():
    assert infer_whale_direction(_event(direction="sell")) == "sell"
    ev = _event(direction="spike", source="volume_spike")
    assert infer_whale_direction(ev, candles=_candles_with_spike(bullish=True)) == "buy"


def test_cooldown_blocks_rapid_follows():
    cd = WhaleFollowCooldown(cooldown_sec=300, max_per_hour=5)
    ok, _ = cd.can_follow("ETH")
    assert ok
    cd.record_follow("ETH")
    ok, reason = cd.can_follow("ETH")
    assert not ok
    assert "cooldown" in reason


def test_hourly_cap():
    cd = WhaleFollowCooldown(cooldown_sec=0, max_per_hour=2)
    cd.record_follow("BTC")
    cd.record_follow("BTC")
    ok, reason = cd.can_follow("BTC")
    assert not ok
    assert "hourly cap" in reason


def test_resolve_follow_route_buy_with_usd():
    holdings = {"USD": 1000.0, "ETH": 0.0}
    route = resolve_follow_route("buy", "ETH", holdings, lambda a, b: object())
    assert route == ("USD", "ETH")


def test_resolve_follow_route_sell_needs_holding():
    assert resolve_follow_route("sell", "ETH", {"USD": 100}, lambda a, b: object()) is None
    route = resolve_follow_route(
        "sell", "ETH", {"ETH": 2.0}, lambda a, b: a == "ETH" and b == "USD"
    )
    assert route == ("ETH", "USD")


def test_evaluate_skips_unclear_direction():
    ev = _event(direction="spike", source="volume_spike")
    cd = WhaleFollowCooldown(cooldown_sec=0, max_per_hour=5)
    flat = pd.DataFrame([{"open": 100, "close": 100.01, "volume": 1}] * 5)
    result = evaluate_whale_follow(
        ev,
        holdings={"USD": 5000},
        find_path=lambda a, b: object(),
        candles=flat,
        size_pct=0.1,
        fee_rate=0.004,
        min_usd=50000,
        cooldown=cd,
    )
    assert result.intent is None
    assert "direction unclear" in result.skip_reason


def test_evaluate_emits_intent_when_gates_allow():
    ev = _event(direction="buy", usd_size=120000)
    cd = WhaleFollowCooldown(cooldown_sec=0, max_per_hour=5)
    result = evaluate_whale_follow(
        ev,
        holdings={"USD": 5000, "ETH": 0},
        find_path=lambda a, b: type("R", (), {"hops": 1, "symbols": (f"{a}/USD",)})(),
        candles=_candles_with_spike(bullish=True),
        size_pct=0.12,
        fee_rate=0.004,
        min_usd=50000,
        cooldown=cd,
    )
    assert result.intent is not None
    assert result.intent.from_asset == "USD"
    assert result.intent.to_asset == "ETH"
    assert result.intent.strategy_name == "whale_follow"
    assert "whale-follow" in result.intent.reason


def test_edge_insufficient_blocks_preflight():
    """Tiny momentum + small whale should still fail a strict min-net gate."""
    ev = _event(direction="buy", usd_size=51000)
    gross = estimate_whale_follow_edge(
        ev, candles=_candles_with_spike(bullish=False), fee_rate=0.004, hops=1, min_usd=50000
    )
    floor = fee_floor_edge(0.004, 1) * 1.15
    assert gross >= floor
    pf = PreFlightValidator(
        FeeEngine(None, 0.004, force_static=True),
        slippage_buffer_pct=0.0005,
        min_net_profit_pct=0.05,
    )
    intent = TradeIntent(
        from_asset="USD", to_asset="ETH", reason="x", size_pct=0.1,
        edge=gross, gross_return_pct=gross, strategy_name="whale_follow",
    )
    res = pf.validate(intent, route_symbols=("ETH/USD",), hops=1)
    assert not res.allowed


def test_successful_intent_clears_break_even_preflight():
    ev = _event(direction="buy", usd_size=200000)
    candles = _candles_with_spike(bullish=True)
    gross = estimate_whale_follow_edge(
        ev, candles=candles, fee_rate=0.004, hops=1, min_usd=50000
    )
    pf = PreFlightValidator(
        FeeEngine(None, 0.004, force_static=True),
        slippage_buffer_pct=0.0005,
        min_net_profit_pct=0.0005,
    )
    intent = TradeIntent(
        from_asset="USD", to_asset="ETH", reason="x", size_pct=0.15,
        edge=gross, gross_return_pct=gross, strategy_name="whale_follow",
    )
    res = pf.validate(intent, route_symbols=("ETH/USD",), hops=1, min_net_profit=0.0005)
    assert res.allowed
    assert res.net_return_pct > 0


def test_portfolio_constraints_eth_reserve():
    constraints = PortfolioConstraints(
        min_eth_reserve=0.5, max_alt_allocation_pct=0.25, min_usd_trade=10.0
    )
    intent = TradeIntent(
        from_asset="ETH", to_asset="USD", reason="whale-follow sell",
        size_pct=0.5, edge=0.01, gross_return_pct=0.01, strategy_name="whale_follow",
    )
    holdings = {"ETH": 0.6, "USD": 1000}
    prices = {"ETH": 3000, "USD": 1}
    result = constraints.validate_intent(intent, holdings, prices, required_edge=0.005)
    assert result.allowed
    assert result.size_pct < 0.5
