"""Tests for bot.verifier.live_tag — fast Discord trade footer."""

from __future__ import annotations

import pytest

from bot.fee_engine import FeeEngine
from bot.preflight import PreFlightValidator
from bot.verifier.kraken import PublicKraken
from bot.verifier.live_tag import build_live_verify_tag
from bot.verifier.models import Verdict


class _FakeKrakenExchange:
    def __init__(self):
        self.markets = {
            "ETH/USD": {"taker": 0.0026, "symbol": "ETH/USD", "active": True},
        }

    def load_markets(self):
        return self.markets

    def fetch_ticker(self, symbol):
        return {"last": 3000.0, "quoteVolume": 50_000_000}

    def fetch_trading_fees(self):
        import ccxt
        raise ccxt.AuthenticationError("no auth")


class _Markets:
    def symbol_exists(self, symbol: str) -> bool:
        return symbol == "ETH/USD"


@pytest.fixture
def single_leg_trade() -> dict:
    return {
        "from_asset": "USD",
        "to_asset": "ETH",
        "symbol": "ETH/USD",
        "side": "buy",
        "price": 3000.0,
        "from_qty": 100.0,
        "quote_qty": 100.0,
        "fee_usd": 0.26,
        "gain_loss": 1.5,
        "edge": 0.01,
        "gross_return_pct": 0.012,
        "hops": 1,
        "type": "single",
        "strategy_name": "cross_momentum",
        "size_pct": 0.1,
    }


def test_live_tag_confirm_single_leg(single_leg_trade) -> None:
    exchange = _FakeKrakenExchange()
    kraken = PublicKraken(exchange=exchange, timeout_ms=2000)
    fee_engine = FeeEngine(exchange, 0.0026, force_static=True)
    preflight = PreFlightValidator(fee_engine, 0.0005, 0.0005)
    result = build_live_verify_tag(
        single_leg_trade,
        markets=_Markets(),
        kraken=kraken,
        fee_engine=fee_engine,
        preflight=preflight,
        usd_prices={"USD": 1.0, "ETH": 3000.0},
    )
    assert result.verdict == Verdict.CONFIRM
    assert result.tag.startswith("✓ Live-viable")
    assert "Kraken" in result.tag


def test_live_tag_multi_hop_uncertain(single_leg_trade) -> None:
    trade = dict(single_leg_trade)
    trade.update({"hops": 3, "type": "multi_hop", "legs": [{}, {}, {}]})
    result = build_live_verify_tag(trade, markets=_Markets(), skip_kraken=True)
    assert result.verdict == Verdict.UNCERTAIN
    assert "multi-hop" in result.tag.lower()


def test_live_tag_deny_bad_price(single_leg_trade) -> None:
    exchange = _FakeKrakenExchange()
    kraken = PublicKraken(exchange=exchange, timeout_ms=2000)
    trade = dict(single_leg_trade)
    trade["price"] = 4000.0
    result = build_live_verify_tag(
        trade,
        markets=_Markets(),
        kraken=kraken,
        skip_kraken=False,
    )
    assert result.verdict == Verdict.DENY
    assert result.tag.startswith("✗")


def test_live_tag_skip_kraken_uses_fee_engine(single_leg_trade) -> None:
    exchange = _FakeKrakenExchange()
    fee_engine = FeeEngine(exchange, 0.0026, force_static=True)
    preflight = PreFlightValidator(fee_engine, 0.0005, 0.0005)
    result = build_live_verify_tag(
        single_leg_trade,
        markets=_Markets(),
        fee_engine=fee_engine,
        preflight=preflight,
        skip_kraken=True,
        usd_prices={"USD": 1.0},
    )
    assert result.verdict == Verdict.CONFIRM
    assert "fee engine" in result.source or "Live-viable" in result.tag


def test_public_kraken_symbol_exists_for_xstock(monkeypatch) -> None:
    from bot.verifier.kraken import PublicKraken

    class _CryptoOnlyExchange:
        markets = {"ETH/USD": {"active": True}}

        def load_markets(self):
            return self.markets

    kraken = PublicKraken(exchange=_CryptoOnlyExchange(), timeout_ms=2000)
    monkeypatch.setattr(
        "bot.verifier.kraken.PublicKraken._tokenized_symbols",
        lambda self: frozenset({"TSLAX/USD", "AAPLX/USD"}),
    )
    assert kraken.symbol_exists("TSLAx/USD")
    assert not kraken.symbol_exists("FAKEx/USD")


def test_live_tag_equity_dca_not_denied_as_missing_on_kraken() -> None:
    trade = {
        "from_asset": "USD",
        "to_asset": "TSLAx",
        "symbol": "TSLAx/USD",
        "side": "buy",
        "price": 400.0,
        "strategy_name": "equity_dca",
        "is_accumulation": True,
        "hops": 1,
        "type": "single",
    }
    result = build_live_verify_tag(trade, skip_kraken=True)
    assert result.verdict == Verdict.CONFIRM
    assert "DCA" in result.tag
