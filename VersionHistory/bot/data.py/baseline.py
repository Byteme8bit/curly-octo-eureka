"""Kraken market data with timeout-aware retries and graceful fallbacks."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, TypeVar

import ccxt
import pandas as pd

from config import Settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Exceptions that mean "try again" — timeouts, transient connectivity, rate limits
_RETRYABLE = (
    ccxt.NetworkError,
    ccxt.RequestTimeout,
    ccxt.ExchangeNotAvailable,
    ccxt.DDoSProtection,
)


class KrakenData:
    def __init__(self, settings: Settings):
        config: dict = {
            "enableRateLimit": True,
            "timeout": settings.kraken_request_timeout_ms,
        }
        if settings.api_key and settings.api_secret:
            config["apiKey"] = settings.api_key
            config["secret"] = settings.api_secret
        self.exchange = ccxt.kraken(config)
        self.usd_symbols = settings.usd_symbols
        self.candle_timeframe = settings.candle_timeframe
        self.candle_limit = settings.candle_limit
        self.momentum_timeframes = settings.momentum_timeframes
        self._workers = min(8, max(2, len(self.usd_symbols)))
        self._max_retries = max(0, settings.kraken_max_retries)
        self._retry_backoff = max(0.1, settings.kraken_retry_backoff_sec)
        # Cached last-good values for graceful degradation when all retries fail
        self._ticker_cache: dict[str, float] = {}
        self._candle_cache: dict[tuple[str, str], pd.DataFrame] = {}

    def _retry(self, label: str, fn: Callable[[], T]) -> T:
        """Run fn with timeout-aware retries. Last exception is re-raised."""
        attempts = self._max_retries + 1
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return fn()
            except _RETRYABLE as exc:
                last_exc = exc
                if attempt >= attempts:
                    break
                # Exponential-ish backoff: 0.75s, 1.5s, 3s, ...
                wait = self._retry_backoff * (2 ** (attempt - 1))
                logger.warning(
                    "Kraken %s timed out (attempt %d/%d): %s — retrying in %.1fs",
                    label, attempt, attempts, type(exc).__name__, wait,
                )
                time.sleep(wait)
        assert last_exc is not None
        raise last_exc

    def fetch_ticker(self, symbol: str) -> float:
        try:
            price = float(
                self._retry(
                    f"fetch_ticker({symbol})",
                    lambda: self.exchange.fetch_ticker(symbol)["last"],
                )
            )
            self._ticker_cache[symbol] = price
            return price
        except _RETRYABLE as exc:
            cached = self._ticker_cache.get(symbol)
            if cached is not None:
                logger.warning(
                    "Kraken fetch_ticker(%s) failed after retries (%s); using cached %.6f",
                    symbol, type(exc).__name__, cached,
                )
                return cached
            raise

    def fetch_tickers(self, symbols: list[str]) -> dict[str, float]:
        if not symbols:
            return {}
        try:
            tickers = self._retry(
                f"fetch_tickers({len(symbols)})",
                lambda: self.exchange.fetch_tickers(symbols),
            )
            prices = {symbol: float(tickers[symbol]["last"]) for symbol in symbols}
            self._ticker_cache.update(prices)
            return prices
        except _RETRYABLE as exc:
            cached = {s: self._ticker_cache[s] for s in symbols if s in self._ticker_cache}
            missing = [s for s in symbols if s not in cached]
            if cached:
                logger.warning(
                    "Kraken fetch_tickers failed after retries (%s); using %d cached, %d missing",
                    type(exc).__name__, len(cached), len(missing),
                )
                return cached
            raise

    def fetch_usd_prices(self, assets: list[str]) -> dict[str, float]:
        symbols = [f"{a}/USD" for a in assets if a != "USD"]
        tickers = self.fetch_tickers(symbols)
        prices = {"USD": 1.0}
        for sym, price in tickers.items():
            prices[sym.split("/")[0]] = price
        return prices

    def fetch_candles(self, symbol: str, timeframe: str | None = None) -> pd.DataFrame:
        tf = timeframe or self.candle_timeframe
        key = (symbol, tf)
        try:
            raw = self._retry(
                f"fetch_ohlcv({symbol},{tf})",
                lambda: self.exchange.fetch_ohlcv(symbol, timeframe=tf, limit=self.candle_limit),
            )
            df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            self._candle_cache[key] = df
            return df
        except _RETRYABLE as exc:
            cached = self._candle_cache.get(key)
            if cached is not None:
                logger.warning(
                    "Kraken fetch_candles(%s,%s) failed after retries (%s); using cached %d rows",
                    symbol, tf, type(exc).__name__, len(cached),
                )
                return cached
            raise

    def fetch_all_candles(self) -> dict[str, pd.DataFrame]:
        candles: dict[str, pd.DataFrame] = {}
        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            futures = {pool.submit(self.fetch_candles, s): s for s in self.usd_symbols}
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    candles[symbol] = future.result()
                except Exception as exc:
                    logger.warning("fetch_all_candles(%s) gave up: %s", symbol, exc)
        return candles

    def fetch_candles_by_timeframe(self, timeframe: str) -> dict[str, pd.DataFrame]:
        candles: dict[str, pd.DataFrame] = {}
        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            futures = {
                pool.submit(self.fetch_candles, s, timeframe): s for s in self.usd_symbols
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    candles[symbol] = future.result()
                except Exception as exc:
                    logger.warning(
                        "fetch_candles_by_timeframe(%s,%s) gave up: %s", symbol, timeframe, exc
                    )
        return candles

    def fetch_multi_timeframe_candles(self) -> dict[str, dict[str, pd.DataFrame]]:
        """Return {timeframe: {symbol: DataFrame}} for momentum strategies."""
        result: dict[str, dict[str, pd.DataFrame]] = {}
        for tf in self.momentum_timeframes:
            result[tf] = self.fetch_candles_by_timeframe(tf)
        return result

    def fetch_pair_prices(self, symbols: list[str]) -> dict[str, float]:
        if not symbols:
            return {}
        return self.fetch_tickers(symbols)
