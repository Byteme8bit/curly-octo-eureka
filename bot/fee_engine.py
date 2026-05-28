"""Dynamic maker/taker fee lookup with caching."""

from __future__ import annotations

import logging
import time

import ccxt

logger = logging.getLogger(__name__)


class FeeEngine:
    """Fetch and cache per-symbol taker fees from the exchange API."""

    def __init__(self, exchange: ccxt.kraken, default_taker: float, cache_ttl_sec: int = 3600):
        self.exchange = exchange
        self.default_taker = default_taker
        self.cache_ttl_sec = cache_ttl_sec
        self._fee_cache: dict[str, tuple[float, float]] = {}  # symbol -> (fee, monotonic_ts)
        self._schedule_loaded = False
        self._pair_fee: dict[str, float] = {}

    def _load_schedule(self) -> None:
        if self._schedule_loaded:
            return
        try:
            fees = self.exchange.fetch_trading_fees()
            for symbol, info in fees.items():
                if not isinstance(info, dict):
                    continue
                taker = info.get("taker")
                if taker is not None:
                    self._pair_fee[symbol] = float(taker)
            self._schedule_loaded = True
        except Exception:
            logger.warning("Could not fetch trading fees — using default taker rate")

    def taker_fee(self, symbol: str) -> float:
        now = time.monotonic()
        cached = self._fee_cache.get(symbol)
        if cached and (now - cached[1]) < self.cache_ttl_sec:
            return cached[0]

        self._load_schedule()
        fee = self._pair_fee.get(symbol, self.default_taker)
        self._fee_cache[symbol] = (fee, now)
        return fee

    def compounded_taker_cost(self, symbols: tuple[str, ...]) -> float:
        """
        Compounded fee cost across sequential legs.
        Returns total fee drag as a fraction (e.g. 0.0078 for ~0.78%).
        """
        if not symbols:
            return 0.0
        retain = 1.0
        for symbol in symbols:
            retain *= 1.0 - self.taker_fee(symbol)
        return 1.0 - retain

    def compounded_fee_pct(self, symbols: tuple[str, ...]) -> float:
        return self.compounded_taker_cost(symbols)
