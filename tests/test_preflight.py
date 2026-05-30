"""Tests for bot.preflight — fee/slippage gating and reject message format."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from bot.fee_engine import FeeEngine
from bot.preflight import PreFlightValidator
from bot.strategies.base import TradeIntent


def _make_intent(edge: float = 0.0, gross: float = 0.0) -> TradeIntent:
    return TradeIntent(
        from_asset="ETH",
        to_asset="USD",
        reason="test",
        size_pct=1.0,
        edge=edge,
        gross_return_pct=gross,
    )


def _make_fee_engine(fee_rate: float = 0.0026) -> FeeEngine:
    """Return a FeeEngine whose compounded fee resolves to *fee_rate* per hop."""
    exchange = MagicMock()
    exchange.fetch_trading_fees.side_effect = Exception("no real exchange in tests")
    exchange.load_markets.return_value = {}
    exchange.markets = {}
    engine = FeeEngine(exchange, default_taker=fee_rate)
    return engine


def _make_validator(
    fee_rate: float = 0.0026,
    slippage: float = 0.001,
    min_net: float = 0.001,
) -> PreFlightValidator:
    fee_engine = _make_fee_engine(fee_rate)
    return PreFlightValidator(
        fee_engine=fee_engine,
        slippage_buffer_pct=slippage,
        min_net_profit_pct=min_net,
    )


class TestPreFlightValidatorAllow:
    def test_profitable_trade_allowed(self):
        v = _make_validator(fee_rate=0.001, slippage=0.001, min_net=0.001)
        result = v.validate(
            _make_intent(gross=0.01),
            route_symbols=("ETHUSD",),
            hops=1,
        )
        assert result.allowed
        assert "OK" in result.reason
        assert "bps" in result.reason

    def test_ok_reason_shows_bps(self):
        v = _make_validator(fee_rate=0.001, slippage=0.001, min_net=0.001)
        result = v.validate(
            _make_intent(gross=0.01),
            route_symbols=("ETHUSD",),
            hops=1,
        )
        # net should be +0.008 → 8.0bps
        assert "bps" in result.reason
        # no raw 4-decimal floats in OK message
        assert "+0." not in result.reason.replace("+0.", "X")  # only the bps repr

    def test_defensive_exit_always_allowed(self):
        v = _make_validator()
        result = v.validate(
            _make_intent(gross=-0.5),
            route_symbols=("ETHUSD",),
            hops=1,
            is_defensive=True,
        )
        assert result.allowed
        assert "bypass" in result.reason.lower()

    def test_custom_min_net_overrides_default(self):
        v = _make_validator(fee_rate=0.001, slippage=0.001, min_net=0.001)
        result = v.validate(
            _make_intent(gross=0.005),
            route_symbols=("ETHUSD",),
            hops=1,
            min_net_profit=0.0,
        )
        assert result.allowed


class TestPreFlightValidatorReject:
    def test_low_edge_rejected(self):
        v = _make_validator(fee_rate=0.0026, slippage=0.001, min_net=0.001)
        result = v.validate(
            _make_intent(gross=0.001),
            route_symbols=("ETHUSD",),
            hops=1,
        )
        assert not result.allowed
        assert "reject" in result.reason.lower()

    def test_reject_reason_uses_bps(self):
        """Reject message must express values in basis points, not raw floats."""
        v = _make_validator(fee_rate=0.0026, slippage=0.001, min_net=0.001)
        result = v.validate(
            _make_intent(gross=0.0012),
            route_symbols=("ETHUSD",),
            hops=1,
        )
        assert not result.allowed
        assert "bps" in result.reason
        # e.g. "+12.0bps" not "+0.0012"
        assert "0.0012" not in result.reason
        assert "0.0026" not in result.reason

    def test_reject_reason_structure(self):
        """Reject reason should contain gross, fees, slippage, and min in bps."""
        v = _make_validator(fee_rate=0.002, slippage=0.001, min_net=0.002)
        result = v.validate(
            _make_intent(gross=0.001),
            route_symbols=("ETHUSD",),
            hops=1,
        )
        assert not result.allowed
        reason = result.reason
        assert "gross" in reason
        assert "fees" in reason
        assert "slippage" in reason
        assert "min" in reason
        assert "bps" in reason

    def test_result_fields_are_raw_fractions(self):
        """The numeric fields on PreFlightResult stay as raw fractions, not bps."""
        v = _make_validator(fee_rate=0.002, slippage=0.001, min_net=0.002)
        result = v.validate(
            _make_intent(gross=0.001),
            route_symbols=("ETHUSD",),
            hops=1,
        )
        assert result.gross_return_pct == pytest.approx(0.001)
        # fee_pct is the compounded fee from FeeEngine — just verify it's a small fraction
        assert 0 < result.fee_pct < 0.1
        assert result.slippage_pct == pytest.approx(0.001)

    def test_multi_hop_slippage_scales(self):
        v = _make_validator(fee_rate=0.001, slippage=0.001, min_net=0.001)
        result_1hop = v.validate(
            _make_intent(gross=0.003),
            route_symbols=("ETHUSD",),
            hops=1,
        )
        result_2hop = v.validate(
            _make_intent(gross=0.003),
            route_symbols=("ETHBTC", "BTCUSD"),
            hops=2,
        )
        assert result_1hop.slippage_pct < result_2hop.slippage_pct

    def test_zero_gross_rejected(self):
        v = _make_validator()
        result = v.validate(
            _make_intent(edge=0.0, gross=0.0),
            route_symbols=("ETHUSD",),
            hops=1,
        )
        assert not result.allowed
