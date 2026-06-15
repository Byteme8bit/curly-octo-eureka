"""Kraken market data with timeout-aware retries and graceful fallbacks."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, TypeVar

import ccxt
import pandas as pd

from bot.equities import (
    fetch_equity_ohlcv,
    fetch_equity_ticker,
    inject_equity_markets,
    is_equity_symbol,
)
from config import Settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Kraken account balances with no USD tradable pair (e.g. fee credits).
_NON_TRADABLE_ASSETS = frozenset({"KFEE"})

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
        self.equity_assets = getattr(settings, "equity_assets", frozenset())
        self._equity_symbols = set(getattr(settings, "equity_usd_symbols", ()) or ())
        if getattr(settings, "enable_equities", False) and self._equity_symbols:
            self._load_equity_markets()
        self.candle_timeframe = settings.candle_timeframe
        self.candle_limit = settings.candle_limit
        self.momentum_timeframes = settings.momentum_timeframes
        self._workers = min(8, max(2, len(self.usd_symbols)))
        self._max_retries = max(0, settings.kraken_max_retries)
        self._retry_backoff = max(0.1, settings.kraken_retry_backoff_sec)
        # Cached last-good values for graceful degradation when all retries fail
        self._ticker_cache: dict[str, float] = {}
        self._candle_cache: dict[tuple[str, str], pd.DataFrame] = {}

    def _load_equity_markets(self) -> None:
        from bot.equities import fetch_tokenized_pairs

        try:
            # Crypto ccxt markets must load first; inject_equity_markets only merges xStocks.
            self.exchange.load_markets()
            pairs = fetch_tokenized_pairs()
            inject_equity_markets(
                self.exchange, pairs, tuple(self._equity_symbols)
            )
            logger.info(
                "Loaded %d Kraken xStock USD pairs into market registry",
                len(self._equity_symbols),
            )
        except Exception as exc:
            logger.warning("Failed to load Kraken xStock markets: %s", exc)

    def _is_equity(self, symbol: str) -> bool:
        return symbol in self._equity_symbols or is_equity_symbol(
            symbol, self.equity_assets
        )

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
            if self._is_equity(symbol):
                price = fetch_equity_ticker(symbol)
            else:
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
        equity = [s for s in symbols if self._is_equity(s)]
        crypto = [s for s in symbols if not self._is_equity(s)]
        prices: dict[str, float] = {}
        if crypto:
            try:
                tickers = self._retry(
                    f"fetch_tickers({len(crypto)})",
                    lambda: self.exchange.fetch_tickers(crypto),
                )
                prices.update(
                    {symbol: float(tickers[symbol]["last"]) for symbol in crypto}
                )
            except _RETRYABLE as exc:
                cached = {s: self._ticker_cache[s] for s in crypto if s in self._ticker_cache}
                missing = [s for s in crypto if s not in cached]
                if cached:
                    logger.warning(
                        "Kraken fetch_tickers failed after retries (%s); using %d cached, %d missing",
                        type(exc).__name__,
                        len(cached),
                        len(missing),
                    )
                    prices.update(cached)
                else:
                    raise
        for symbol in equity:
            try:
                prices[symbol] = fetch_equity_ticker(symbol)
            except Exception as exc:
                cached = self._ticker_cache.get(symbol)
                if cached is not None:
                    logger.warning(
                        "Equity ticker %s failed (%s); using cached %.4f",
                        symbol,
                        exc,
                        cached,
                    )
                    prices[symbol] = cached
                else:
                    logger.warning("Equity ticker %s failed (%s); skipping", symbol, exc)
        if prices:
            self._ticker_cache.update(prices)
        return prices

    def _has_usd_market(self, asset: str) -> bool:
        if asset in _NON_TRADABLE_ASSETS:
            return False
        if asset == "USD":
            return True
        symbol = f"{asset}/USD"
        markets = self.exchange.markets
        if not markets:
            markets = self.exchange.load_markets()
        return symbol in markets

    def fetch_usd_prices(self, assets: list[str]) -> dict[str, float]:
        prices: dict[str, float] = {"USD": 1.0}
        symbols: list[str] = []
        for asset in assets:
            if asset == "USD":
                continue
            if not self._has_usd_market(asset):
                logger.debug(
                    "Skipping USD price for %s — no Kraken USD market (non-tradable balance)",
                    asset,
                )
                continue
            symbols.append(f"{asset}/USD")
        if not symbols:
            return prices
        tickers = self.fetch_tickers(symbols)
        for sym, price in tickers.items():
            prices[sym.split("/")[0]] = price
        return prices

    def fetch_candles(self, symbol: str, timeframe: str | None = None) -> pd.DataFrame:
        tf = timeframe or self.candle_timeframe
        key = (symbol, tf)
        try:
            if self._is_equity(symbol):
                raw = fetch_equity_ohlcv(
                    symbol, timeframe=tf, limit=self.candle_limit
                )
            else:
                raw = self._retry(
                    f"fetch_ohlcv({symbol},{tf})",
                    lambda: self.exchange.fetch_ohlcv(
                        symbol, timeframe=tf, limit=self.candle_limit
                    ),
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

    def fetch_trades(self, symbol: str, limit: int = 60) -> list[dict]:
        """Recent public trades for whale-watch (no API key required)."""
        cap = max(1, min(limit, 500))
        try:
            return self._retry(
                f"fetch_trades({symbol})",
                lambda: self.exchange.fetch_trades(symbol, limit=cap),
            )
        except _RETRYABLE as exc:
            logger.warning(
                "Kraken fetch_trades(%s) failed after retries (%s); skipping whale trade scan",
                symbol,
                type(exc).__name__,
            )
            return []
