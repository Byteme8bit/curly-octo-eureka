"""Tests for bot.verifier — independent trade audit."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import replace

import pytest

from bot.trade_log import ReceiptWriter
from bot.trade_log import trade_narrative
from bot.verifier.checks import (
    check_correlation,
    check_fee_realism,
    check_market_reality,
    check_multi_hop,
    check_price_plausibility,
)
from bot.verifier.config import VerifierSettings
from bot.verifier.core import Verifier
from bot.verifier.kraken import PublicKraken
from bot.verifier.models import Verdict


class _FakeKrakenExchange:
    """ccxt-shaped stub for verifier price/fee checks."""

    def __init__(self, markets: dict | None = None):
        self.markets = markets or {
            "ETH/USD": {"taker": 0.0026, "maker": 0.0016, "symbol": "ETH/USD"},
            "ADA/USD": {"taker": 0.0026, "maker": 0.0016, "symbol": "ADA/USD"},
            "UNI/ETH": {"taker": 0.0026, "maker": 0.0016, "symbol": "UNI/ETH"},
        }
        self._ohlcv_prices = {
            "ETH/USD": (3000, 3010, 2990),
            "ADA/USD": (0.45, 0.46, 0.44),
            "UNI/ETH": (0.00149, 0.00150, 0.00148),
        }
        self._tickers = {
            "ETH/USD": {"last": 3000, "quoteVolume": 50_000_000},
            "ADA/USD": {"last": 0.45, "quoteVolume": 5_000_000},
            "UNI/ETH": {"last": 0.00149, "quoteVolume": 200_000},
        }

    def load_markets(self):
        return self.markets

    def fetch_ohlcv(self, symbol, timeframe="5m", since=None, limit=12):
        close, high, low = self._ohlcv_prices.get(symbol, (1.0, 1.01, 0.99))
        ts = since or 1_700_000_000_000
        # Align candle start to 5m bucket.
        ts = (ts // 300_000) * 300_000
        return [[ts, close, high, low, close, 100]]

    def fetch_ticker(self, symbol):
        return self._tickers.get(symbol, {"last": 1.0, "quoteVolume": 1_000_000})

    def fetch_trading_fees(self):
        import ccxt
        raise ccxt.AuthenticationError("no auth")


@pytest.fixture
def verifier_env(tmp_path: Path) -> VerifierSettings:
    state = {
        "balances": {"ETH": 1.0, "USD": 100.0, "ADA": 0.0},
        "cost_basis": {},
        "trades": [],
    }
    state_file = tmp_path / ".paper_state.json"
    state_file.write_text(json.dumps(state), encoding="utf-8")
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    logs = tmp_path / "logs"
    logs.mkdir()
    return VerifierSettings(
        bot_root=tmp_path,
        state_file=state_file,
        paper_portfolio_file=tmp_path / "paper_portfolio.json",
        receipts_dir=receipts,
        log_dir=logs,
        runtime_log=logs / "runtime.log",
        reports_dir=tmp_path / "reports",
        min_eth_reserve=0.25,
        max_alt_allocation_pct=0.40,
        min_usd_trade=10.0,
        fee_rate=0.0026,
        slippage_buffer_pct=0.0005,
        min_net_profit_pct=0.0005,
        min_trade_edge=0.006,
        price_tolerance_pct=0.02,
        slippage_assume_pct=0.005,
        fee_tolerance_rel=0.15,
        liquidity_volume_warn_ratio=0.01,
        log_time_window_minutes=30,
        skip_kraken=True,
        kraken_timeout_ms=5000,
    )


def _good_trade() -> dict:
    return {
        "time": datetime(2026, 5, 31, 13, 44, 54, tzinfo=timezone.utc).isoformat(),
        "symbol": "ADA/USD",
        "side": "buy",
        "type": "usd",
        "from_asset": "USD",
        "to_asset": "ADA",
        "from_qty": 50.0,
        "to_qty": 110.0,
        "price": 0.45,
        "quote_qty": 50.0,
        "size_pct": 0.5,
        "fee_quote": 0.13,
        "fee_usd": 0.13,
        "reason": "momentum leader rotation",
        "gain_loss": 0.0,
        "hops": 1,
        "edge": 0.01,
        "gross_return_pct": 0.01,
        "is_defensive": False,
    }


def _bad_price_trade() -> dict:
    t = _good_trade()
    t["price"] = 0.90  # double market
    return t


def _triangular_trade() -> dict:
    return {
        "time": datetime(2026, 5, 31, 13, 44, 54, tzinfo=timezone.utc).isoformat(),
        "symbol": "UNI/ETH",
        "side": "buy",
        "type": "cross",
        "from_asset": "ETH",
        "to_asset": "UNI",
        "from_qty": 0.1,
        "to_qty": 66.8,
        "price": 0.001493,
        "quote_qty": 0.1,
        "size_pct": 0.1,
        "fee_usd": 0.52,
        "reason": "triangular arb leg 1/3 — loop ETH->UNI->AAVE->ETH gross +0.0063",
        "gain_loss": -0.52,
        "hops": 1,
        "strategy_name": "triangular_arbitrage",
        "edge": 0.003,
        "gross_return_pct": 0.006,
        "is_defensive": False,
    }


def test_good_trade_confirm(verifier_env: VerifierSettings, tmp_path: Path):
    trade = _good_trade()
    state = json.loads(verifier_env.state_file.read_text())
    state["trades"] = [trade]
    verifier_env.state_file.write_text(json.dumps(state), encoding="utf-8")

    writer = ReceiptWriter(verifier_env.receipts_dir)
    trade["receipt_file"] = str(writer.save(trade))

    log_file = verifier_env.log_dir / "bot.log"
    log_file.write_text(f"MARKET CHECK\n{trade_narrative(trade)}\n", encoding="utf-8")

    settings = verifier_env
    kraken = PublicKraken(_FakeKrakenExchange())
    settings_live = replace(settings, skip_kraken=False)

    v = Verifier(settings_live)
    v._kraken = kraken
    report = v.run(last=1)

    assert report.trades_reviewed == 1
    assert report.trade_verdicts[0].verdict == Verdict.CONFIRM


def test_bad_price_deny(verifier_env: VerifierSettings):
    trade = _bad_price_trade()
    kraken = PublicKraken(_FakeKrakenExchange())
    result = check_price_plausibility(trade, kraken, verifier_env)
    assert result.verdict == Verdict.DENY


def test_triangular_uncertain(verifier_env: VerifierSettings):
    trade = _triangular_trade()
    result = check_multi_hop(trade)
    assert result.verdict == Verdict.UNCERTAIN


def test_missing_receipt_deny(verifier_env: VerifierSettings):
    trade = _good_trade()
    result = check_correlation(trade, verifier_env)
    assert result.verdict == Verdict.DENY


def test_market_reality_with_mock_ccxt(verifier_env: VerifierSettings):
    trade = _good_trade()
    kraken = PublicKraken(_FakeKrakenExchange())
    assert check_market_reality(trade, kraken).verdict == Verdict.CONFIRM

    trade["symbol"] = "FAKE/USD"
    assert check_market_reality(trade, kraken).verdict == Verdict.DENY


def test_fee_realism_tolerance(verifier_env: VerifierSettings):
    trade = _good_trade()
    kraken = PublicKraken(_FakeKrakenExchange())
    result = check_fee_realism(trade, kraken, verifier_env)
    assert result.verdict in (Verdict.CONFIRM, Verdict.UNCERTAIN)
