"""Tests for Kraken retry-with-backoff (feature 008)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import ccxt
import pytest


@pytest.fixture
def fake_settings():
    class S:
        api_key = ""
        api_secret = ""
        usd_symbols = ("BTC/USD", "ETH/USD")
        candle_timeframe = "5m"
        candle_limit = 60
        momentum_timeframes = ("15m",)
        kraken_request_timeout_ms = 5000
        kraken_max_retries = 2
        kraken_retry_backoff_sec = 0.01  # tiny so tests are fast
    return S()


def test_retry_succeeds_after_one_timeout(fake_settings):
    from bot.data import KrakenData

    with patch("bot.data.ccxt.kraken") as kraken_cls:
        exchange = MagicMock()
        calls = {"n": 0}

        def fake_fetch(symbol):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ccxt.RequestTimeout("timeout")
            return {"last": 12345.0}

        exchange.fetch_ticker.side_effect = fake_fetch
        kraken_cls.return_value = exchange

        data = KrakenData(fake_settings)
        price = data.fetch_ticker("BTC/USD")
        assert price == 12345.0
        assert calls["n"] == 2


def test_retry_gives_up_after_max(fake_settings):
    from bot.data import KrakenData

    with patch("bot.data.ccxt.kraken") as kraken_cls:
        exchange = MagicMock()
        exchange.fetch_ticker.side_effect = ccxt.RequestTimeout("timeout")
        kraken_cls.return_value = exchange

        data = KrakenData(fake_settings)
        with pytest.raises(ccxt.RequestTimeout):
            data.fetch_ticker("BTC/USD")

        # 1 initial + 2 retries = 3 calls
        assert exchange.fetch_ticker.call_count == 3


def test_ticker_cache_fallback_after_all_retries(fake_settings):
    from bot.data import KrakenData

    with patch("bot.data.ccxt.kraken") as kraken_cls:
        exchange = MagicMock()
        # First call succeeds (populates cache); second fails always
        exchange.fetch_ticker.side_effect = [
            {"last": 100.0},
            ccxt.RequestTimeout("t"),
            ccxt.RequestTimeout("t"),
            ccxt.RequestTimeout("t"),
        ]
        kraken_cls.return_value = exchange

        data = KrakenData(fake_settings)
        first = data.fetch_ticker("BTC/USD")
        assert first == 100.0
        # Second call: all retries fail; should fall back to cached 100.0
        cached = data.fetch_ticker("BTC/USD")
        assert cached == 100.0


def test_no_retry_on_non_retryable_exception(fake_settings):
    from bot.data import KrakenData

    with patch("bot.data.ccxt.kraken") as kraken_cls:
        exchange = MagicMock()
        exchange.fetch_ticker.side_effect = ValueError("bad payload")
        kraken_cls.return_value = exchange

        data = KrakenData(fake_settings)
        with pytest.raises(ValueError):
            data.fetch_ticker("BTC/USD")
        assert exchange.fetch_ticker.call_count == 1


def test_fetch_usd_prices_skips_kfee(fake_settings):
    from bot.data import KrakenData

    with patch("bot.data.ccxt.kraken") as kraken_cls:
        exchange = MagicMock()
        exchange.markets = {
            "ETH/USD": {"base": "ETH", "quote": "USD"},
            "BTC/USD": {"base": "BTC", "quote": "USD"},
        }
        exchange.fetch_tickers.return_value = {
            "ETH/USD": {"last": 3000.0},
            "BTC/USD": {"last": 60000.0},
        }
        kraken_cls.return_value = exchange

        data = KrakenData(fake_settings)
        prices = data.fetch_usd_prices(["USD", "ETH", "KFEE", "BTC"])

        assert prices == {"USD": 1.0, "ETH": 3000.0, "BTC": 60000.0}
        called_symbols = exchange.fetch_tickers.call_args[0][0]
        assert "KFEE/USD" not in called_symbols


def test_fetch_usd_prices_skips_asset_without_market(fake_settings):
    from bot.data import KrakenData

    with patch("bot.data.ccxt.kraken") as kraken_cls:
        exchange = MagicMock()
        exchange.markets = {"ETH/USD": {"base": "ETH", "quote": "USD"}}
        exchange.fetch_tickers.return_value = {"ETH/USD": {"last": 3000.0}}
        kraken_cls.return_value = exchange

        data = KrakenData(fake_settings)
        prices = data.fetch_usd_prices(["ETH", "NOPE"])

        assert prices == {"USD": 1.0, "ETH": 3000.0}
        called_symbols = exchange.fetch_tickers.call_args[0][0]
        assert "NOPE/USD" not in called_symbols
