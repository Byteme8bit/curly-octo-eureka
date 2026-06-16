"""Public Kraken market data for independent verification (no auth required)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Protocol

import ccxt

from bot.fee_engine import FeeEngine

logger = logging.getLogger(__name__)


class KrakenClient(Protocol):
    def load_markets(self) -> dict: ...
    def fetch_ohlcv(self, symbol: str, timeframe: str = "5m", since: int | None = None, limit: int = 12): ...
    def fetch_ticker(self, symbol: str) -> dict: ...


class PublicKraken:
    """Thin wrapper around ccxt.kraken for verifier price/fee/liquidity checks."""

    def __init__(self, exchange: KrakenClient | None = None, *, timeout_ms: int = 5000):
        if exchange is None:
            exchange = ccxt.kraken({"enableRateLimit": True, "timeout": timeout_ms})
        self.exchange = exchange
        self._fee_engine = FeeEngine(exchange, default_taker=0.0026, force_static=False)
        self._markets_loaded = False
        self._ohlcv_cache: dict[tuple[str, int], tuple[float, float, float]] = {}

    def ensure_markets(self) -> dict:
        if not self._markets_loaded:
            self.exchange.load_markets()
            self._fee_engine._try_public_schedule()
            self._fee_engine._schedule_loaded = True
            self._markets_loaded = True
        return self.exchange.markets or {}

    def symbol_exists(self, symbol: str) -> bool:
        markets = self.ensure_markets()
        return symbol in markets

    def asset_tradeable(self, asset: str) -> bool:
        if asset in ("USD", "USDT", "USDC"):
            return True
        markets = self.ensure_markets()
        return f"{asset}/USD" in markets or f"{asset}/ETH" in markets or f"{asset}/BTC" in markets

    def taker_fee(self, symbol: str) -> float:
        self.ensure_markets()
        return self._fee_engine.taker_fee(symbol)

    def price_range_at(self, symbol: str, trade_time: datetime) -> tuple[float | None, float | None, str]:
        """Return (low, high, detail) for the 5m candle containing trade_time."""
        if trade_time.tzinfo is None:
            trade_time = trade_time.replace(tzinfo=timezone.utc)
        since_ms = int((trade_time.timestamp() - 600) * 1000)
        bucket = since_ms // 300_000
        cache_key = (symbol, bucket)
        if cache_key in self._ohlcv_cache:
            low, high, detail = self._ohlcv_cache[cache_key]
            return low, high, detail

        try:
            candles = self.exchange.fetch_ohlcv(symbol, "5m", since=since_ms, limit=12)
        except Exception as exc:  # noqa: BLE001
            detail = f"OHLCV fetch failed: {type(exc).__name__}"
            self._ohlcv_cache[cache_key] = (None, None, detail)
            return None, None, detail

        if not candles:
            detail = "No OHLCV candles returned"
            self._ohlcv_cache[cache_key] = (None, None, detail)
            return None, None, detail

        trade_ms = int(trade_time.timestamp() * 1000)
        chosen = None
        best_delta = 10**12
        for candle in candles:
            ts, _o, high, low, _c, _v = candle
            if ts <= trade_ms < ts + 300_000:
                chosen = candle
                break
            delta = abs(ts - trade_ms)
            if delta < best_delta:
                best_delta = delta
                chosen = candle

        if chosen is None:
            chosen = candles[0]

        _ts, _o, high, low, _c, _v = chosen
        if best_delta > 600_000 and trade_ms < _ts:
            detail = "OHLCV candles are after trade time — historical data unavailable"
            self._ohlcv_cache[cache_key] = (None, None, detail)
            return None, None, detail
        detail = f"5m candle [{low:.8g}, {high:.8g}]"
        self._ohlcv_cache[cache_key] = (float(low), float(high), detail)
        return float(low), float(high), detail

    def quote_volume_usd(self, symbol: str) -> float | None:
        try:
            ticker = self.exchange.fetch_ticker(symbol)
        except Exception as exc:  # noqa: BLE001
            logger.debug("ticker fetch failed for %s: %s", symbol, exc)
            return None
        quote_vol = ticker.get("quoteVolume")
        if quote_vol is not None:
            return float(quote_vol)
        base_vol = ticker.get("baseVolume")
        last = ticker.get("last")
        if base_vol is not None and last is not None:
            return float(base_vol) * float(last)
        return None
