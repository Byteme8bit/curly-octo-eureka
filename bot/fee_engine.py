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
        """Resolve per-pair taker fees with progressive fallback.

        Priority (best → worst):
          1. Authenticated `fetch_trading_fees()` — personalised to the user's
             30-day volume tier. Requires KRAKEN_API_KEY/SECRET in .env.
          2. Public market metadata from `load_markets()` — Kraken's base
             taker fee per pair, accurate for fresh accounts (0.26% standard).
             No auth required.
          3. Env default `FEE_RATE` — last resort, only if both API calls fail.
        """
        if self._schedule_loaded:
            return

        # 1) Personalised fees (auth-only).
        if self._try_personalised_fees():
            self._schedule_loaded = True
            return

        # 2) Public base-tier schedule from market metadata.
        if self._try_public_schedule():
            self._schedule_loaded = True
            return

        # 3) Last resort — env default for everything.
        logger.warning(
            "Could not load any fee schedule from Kraken; using env default "
            "taker rate %.4f for all pairs", self.default_taker,
        )
        self._schedule_loaded = True  # don't keep retrying every tick

    def _try_personalised_fees(self) -> bool:
        try:
            fees = self.exchange.fetch_trading_fees()
        except ccxt.AuthenticationError:
            return False  # expected when KRAKEN_API_KEY is empty
        except ccxt.PermissionDenied:
            return False  # API key lacks the right permission
        except ccxt.NotSupported:
            # ccxt hasn't implemented this endpoint for the exchange yet
            # (Kraken as of 2026). Public schedule has the same numbers.
            return False
        except Exception as exc:  # noqa: BLE001
            logger.warning("Personalised fee fetch failed (%s); trying public schedule", exc)
            return False
        loaded = 0
        for symbol, info in (fees or {}).items():
            if not isinstance(info, dict):
                continue
            taker = info.get("taker")
            if taker is not None:
                self._pair_fee[symbol] = float(taker)
                loaded += 1
        if loaded:
            sample = self._sample_fees()
            logger.warning(
                "Fee source: PERSONALISED (Kraken auth) — %d pair(s) loaded%s",
                loaded, sample,
            )
            return True
        return False

    def _try_public_schedule(self) -> bool:
        try:
            markets = self.exchange.markets or self.exchange.load_markets()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Public fee schedule load failed (%s); using env default", exc)
            return False
        loaded = 0
        for symbol, market in (markets or {}).items():
            if not isinstance(market, dict):
                continue
            taker = market.get("taker")
            if taker is not None:
                self._pair_fee[symbol] = float(taker)
                loaded += 1
        if loaded:
            sample = self._sample_fees()
            logger.warning(
                "Fee source: PUBLIC (Kraken base-tier, no auth needed) — "
                "%d pair(s) loaded%s",
                loaded, sample,
            )
            return True
        return False

    def _sample_fees(self) -> str:
        """Render a short ' [ETH/USD=0.26%, BTC/USD=0.26%, ...]' suffix for logs."""
        priority = ("ETH/USD", "BTC/USD", "SOL/USD", "ADA/USD")
        samples = []
        for sym in priority:
            if sym in self._pair_fee:
                samples.append(f"{sym}={self._pair_fee[sym] * 100:.2f}%")
        if not samples:
            # Fall back to whatever first 3 we have
            for sym, fee in list(self._pair_fee.items())[:3]:
                samples.append(f"{sym}={fee * 100:.2f}%")
        return f" [{', '.join(samples)}]" if samples else ""

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
