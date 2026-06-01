"""Tests for the real-fee pre-flight gate (feature 030).

Covers the two config root-causes of the fee bleed:
  1. FEE_FORCE_STATIC=1 + FEE_RATE=0.0026 lets sub-breakeven trades through
     because the gate assumes 0.26% fees when the real Kraken taker is ~0.40%.
  2. A zero-edge "probe" can never clear a break-even (net > 0) gate once real
     fees are applied — so the forced probe is safe to leave enabled.
"""
from __future__ import annotations

from bot.fee_engine import FeeEngine
from bot.preflight import PreFlightValidator
from bot.strategies.base import TradeIntent


def _validator(taker: float, min_net: float = 0.0005) -> PreFlightValidator:
    # force_static => FeeEngine returns `taker` for every symbol, no network.
    fee_engine = FeeEngine(exchange=None, default_taker=taker, force_static=True)
    return PreFlightValidator(
        fee_engine, slippage_buffer_pct=0.0005, min_net_profit_pct=min_net
    )


def _intent(gross: float) -> TradeIntent:
    return TradeIntent(
        from_asset="ETH", to_asset="SOL", reason="x",
        size_pct=0.1, edge=gross, gross_return_pct=gross,
    )


def test_static_fee_underprices_a_loser():
    """A 0.30% gross single-leg trade looks profitable at the assumed 0.26% fee."""
    pf = _validator(taker=0.0026)
    # A 0.40% gross single-leg trade clears the optimistic 0.26% gate
    # (net = 0.0040 - 0.0026 - 0.0005 = +0.0009 > min 0.0005) ...
    res = pf.validate(_intent(0.0040), route_symbols=("ETH/USD",), hops=1)
    assert res.allowed, "0.40% gross clears the optimistic 0.26% gate"


def test_real_fee_rejects_the_same_trade():
    """The identical trade is correctly rejected once real 0.40% fees apply."""
    pf = _validator(taker=0.0040)
    res = pf.validate(_intent(0.0040), route_symbols=("ETH/USD",), hops=1)
    assert not res.allowed
    assert res.net_return_pct < 0


def test_zero_edge_probe_blocked_at_breakeven():
    """A zero-gross probe can never clear a net>0 gate after real fees."""
    pf = _validator(taker=0.0040, min_net=0.002)
    res = pf.validate(
        _intent(0.0), route_symbols=("ETH/USD",), hops=1, min_net_profit=0.0
    )
    assert not res.allowed
    assert res.net_return_pct < 0


def test_genuine_edge_probe_allowed_at_breakeven():
    """A probe with real positive net after fees IS allowed (rare, non-losing)."""
    pf = _validator(taker=0.0040)
    res = pf.validate(
        _intent(0.010), route_symbols=("SOL/USD",), hops=1, min_net_profit=0.0
    )
    assert res.allowed
    assert res.net_return_pct > 0
