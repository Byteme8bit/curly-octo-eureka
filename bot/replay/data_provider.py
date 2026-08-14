"""Historical market data provider for replay (KrakenData-compatible surface)."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

_NON_TRADABLE = frozenset({"KFEE"})


def _frames_from_cache(cache: dict, timeframe: str) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for sym, rows in (cache.get("symbols") or {}).items():
        if not rows:
            continue
        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        out[sym] = df.sort_values("timestamp").reset_index(drop=True)
    return out


def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    x = df.set_index("timestamp")
    ohlc = x.resample(rule).agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    ).dropna(subset=["close"])
    ohlc = ohlc.reset_index()
    return ohlc


class HistoricalDataProvider:
    """Serves lookback windows from a cached OHLCV store at a replay index."""

    def __init__(
        self,
        cache: dict,
        *,
        usd_symbols: tuple[str, ...],
        candle_timeframe: str = "5m",
        candle_limit: int = 60,
        momentum_timeframes: tuple[str, ...] = ("15m", "1h"),
        exchange: Any = None,
    ) -> None:
        self.usd_symbols = usd_symbols
        self.candle_timeframe = candle_timeframe
        self.candle_limit = candle_limit
        self.momentum_timeframes = momentum_timeframes
        self.exchange = exchange
        self._base = _frames_from_cache(cache, candle_timeframe)
        self._index = 0
        self._anchor_symbol = self._pick_anchor()
        self._timeline = list(self._base[self._anchor_symbol]["timestamp"]) if self._anchor_symbol else []
        # Precompute multi-TF full series from 5m
        self._by_tf: dict[str, dict[str, pd.DataFrame]] = {candle_timeframe: self._base}
        rule_map = {"15m": "15min", "1h": "1h", "5m": "5min", "1m": "1min"}
        for tf in momentum_timeframes:
            if tf == candle_timeframe:
                continue
            rule = rule_map.get(tf, tf)
            self._by_tf[tf] = {
                sym: _resample(df, rule) for sym, df in self._base.items()
            }

    def _pick_anchor(self) -> str | None:
        for pref in ("ETH/USD", "BTC/USD", "ADA/USD"):
            if pref in self._base and len(self._base[pref]) > 0:
                return pref
        return next(iter(self._base), None)

    @property
    def bar_count(self) -> int:
        # Need candle_limit history before first evaluable bar
        n = len(self._timeline)
        return max(0, n - self.candle_limit)

    def bar_timestamp(self, bar_i: int):
        # bar_i is 0..bar_count-1 mapping to absolute index candle_limit-1 + bar_i
        abs_i = self.candle_limit - 1 + bar_i
        return self._timeline[abs_i]

    def set_bar(self, bar_i: int) -> None:
        self._index = self.candle_limit - 1 + bar_i

    def _window(self, df: pd.DataFrame, abs_i: int | None = None) -> pd.DataFrame:
        i = self._index if abs_i is None else abs_i
        if df.empty:
            return df.copy()
        # Align by timestamp <= current bar time
        ts = self._timeline[i]
        sub = df[df["timestamp"] <= ts].tail(self.candle_limit)
        return sub.reset_index(drop=True)

    def fetch_ticker(self, symbol: str) -> float:
        df = self._base.get(symbol)
        if df is None or df.empty:
            # derive cross from USD legs if possible
            if "/" in symbol:
                base, quote = symbol.split("/", 1)
                b = self.fetch_usd_prices([base]).get(base, 0.0)
                q = 1.0 if quote == "USD" else self.fetch_usd_prices([quote]).get(quote, 0.0)
                if b > 0 and q > 0:
                    return b / q
            raise KeyError(f"no replay data for {symbol}")
        w = self._window(df)
        if w.empty:
            raise KeyError(f"empty window for {symbol}")
        return float(w.iloc[-1]["close"])

    def fetch_tickers(self, symbols: list[str]) -> dict[str, float]:
        out: dict[str, float] = {}
        for s in symbols:
            try:
                out[s] = self.fetch_ticker(s)
            except Exception as exc:  # noqa: BLE001
                logger.debug("ticker miss %s: %s", s, exc)
        return out

    def fetch_usd_prices(self, assets: list[str] | None = None) -> dict[str, float]:
        assets = list(assets or [])
        prices = {"USD": 1.0}
        for a in assets:
            if a in ("USD",) or a in _NON_TRADABLE:
                continue
            sym = f"{a}/USD"
            try:
                prices[a] = self.fetch_ticker(sym)
            except Exception:
                # try via BTC
                try:
                    btc = self.fetch_ticker("BTC/USD")
                    cross = self.fetch_ticker(f"{a}/BTC")
                    prices[a] = btc * cross
                except Exception:
                    prices[a] = 0.0
        # Always include majors present in cache
        for sym in self.usd_symbols:
            asset = sym.split("/")[0]
            if asset not in prices:
                try:
                    prices[asset] = self.fetch_ticker(sym)
                except Exception:
                    pass
        return prices

    def fetch_candles(self, symbol: str, timeframe: str | None = None) -> pd.DataFrame:
        tf = timeframe or self.candle_timeframe
        series = self._by_tf.get(tf, self._base).get(symbol)
        if series is None:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        return self._window(series)

    def fetch_all_candles(self) -> dict[str, pd.DataFrame]:
        return {s: self.fetch_candles(s) for s in self.usd_symbols if s in self._base}

    def fetch_candles_by_timeframe(self, timeframe: str) -> dict[str, pd.DataFrame]:
        return {
            s: self.fetch_candles(s, timeframe)
            for s in self.usd_symbols
            if s in self._by_tf.get(timeframe, self._base)
        }

    def fetch_multi_timeframe_candles(self) -> dict[str, dict[str, pd.DataFrame]]:
        return {tf: self.fetch_candles_by_timeframe(tf) for tf in self.momentum_timeframes}

    def fetch_pair_prices(self, symbols: list[str]) -> dict[str, float]:
        return self.fetch_tickers(symbols)

    def fetch_trades(self, symbol: str, limit: int = 60) -> list[dict]:
        return []
