"""Download and cache Kraken OHLCV for historical replay."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ccxt
import pandas as pd

logger = logging.getLogger(__name__)

# Kraken public OHLCV page size is typically <= 720
_PAGE = 720


def _tf_ms(timeframe: str) -> int:
    unit = timeframe[-1]
    n = int(timeframe[:-1])
    if unit == "m":
        return n * 60_000
    if unit == "h":
        return n * 3_600_000
    if unit == "d":
        return n * 86_400_000
    raise ValueError(f"unsupported timeframe: {timeframe}")


def default_symbols(usd_symbols: tuple[str, ...], stat_arb_pairs) -> list[str]:
    """USD pairs + cross pairs needed for strategies."""
    out: list[str] = []
    seen: set[str] = set()
    for s in usd_symbols:
        s = str(s).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    for item in stat_arb_pairs or ():
        if isinstance(item, str):
            s = item.strip()
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            s = f"{item[0]}/{item[1]}"
        else:
            continue
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    for extra in (
        "ETH/BTC",
        "ADA/ETH",
        "ADA/BTC",
        "SOL/ETH",
        "BTC/USD",
        "ETH/USD",
        "ADA/USD",
        "SOL/USD",
    ):
        if extra not in seen:
            seen.add(extra)
            out.append(extra)
    return out


def fetch_ohlcv_range(
    exchange: ccxt.Exchange,
    symbol: str,
    timeframe: str,
    since_ms: int,
    until_ms: int,
) -> pd.DataFrame:
    """Paginate Kraken public OHLC using the API ``since`` cursor (seconds).

    Kraken returns up to 720 candles and a ``last`` id for the next page.
    """
    interval_map = {
        "1m": 1,
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "1h": 60,
        "4h": 240,
        "1d": 1440,
        "1w": 10080,
    }
    if timeframe not in interval_map:
        raise ValueError(f"unsupported timeframe for Kraken OHLC: {timeframe}")
    interval = interval_map[timeframe]

    market = exchange.market(symbol)
    pair = market.get("id") or market.get("symbol")
    since_sec = int(since_ms // 1000)
    until_sec = int(until_ms // 1000)
    cursor = since_sec
    rows: list[list] = []
    seen: set[int] = set()
    guard = 0
    while cursor < until_sec and guard < 40:
        guard += 1
        resp = exchange.publicGetOhlc({"pair": pair, "interval": interval, "since": cursor})
        time.sleep(exchange.rateLimit / 1000.0 if getattr(exchange, "rateLimit", None) else 0.35)
        result = (resp or {}).get("result") or {}
        # result keys: pair id + 'last'
        last = result.get("last")
        series_key = next((k for k in result.keys() if k != "last"), None)
        batch = result.get(series_key) or [] if series_key else []
        if not batch:
            break
        added = 0
        for item in batch:
            # [time, open, high, low, close, vwap, volume, count]
            ts = int(item[0]) * 1000
            if ts < since_ms or ts > until_ms or ts in seen:
                continue
            seen.add(ts)
            rows.append(
                [
                    ts,
                    float(item[1]),
                    float(item[2]),
                    float(item[3]),
                    float(item[4]),
                    float(item[6]),
                ]
            )
            added += 1
        if last is None:
            break
        next_cursor = int(last)
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if added == 0 and int(batch[-1][0]) * 1000 >= until_ms:
            break

    if not rows:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
    df = df[(df["timestamp"] >= since_ms) & (df["timestamp"] <= until_ms)]
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df.reset_index(drop=True)


def download_replay_cache(
    *,
    symbols: list[str],
    timeframe: str,
    days: int,
    cache_dir: Path,
    exchange: ccxt.Exchange | None = None,
) -> Path:
    """Fetch last N days of OHLCV and write JSON cache. Returns cache path."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=days)
    since_ms = int(since.timestamp() * 1000)
    until_ms = int(until.timestamp() * 1000)

    ex = exchange or ccxt.kraken({"enableRateLimit": True, "timeout": 30000})
    if not getattr(ex, "markets", None):
        ex.load_markets()

    payload: dict = {
        "timeframe": timeframe,
        "days": days,
        "since": since.isoformat(),
        "until": until.isoformat(),
        "symbols": {},
    }
    for sym in symbols:
        try:
            if sym not in ex.markets:
                logger.warning("skip missing market %s", sym)
                continue
            df = fetch_ohlcv_range(ex, sym, timeframe, since_ms, until_ms)
            raw = [
                {
                    "timestamp": int(row["timestamp"].timestamp() * 1000),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                }
                for _, row in df.iterrows()
            ]
            payload["symbols"][sym] = raw
            logger.info("cached %s: %d bars", sym, len(raw))
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed OHLCV %s: %s", sym, exc)

    stamp = until.strftime("%Y%m%dT%H%M%SZ")
    path = cache_dir / f"ohlcv_{days}d_{timeframe}_{stamp}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    latest = cache_dir / "latest.json"
    latest.write_text(json.dumps({"path": str(path)}), encoding="utf-8")
    return path


def load_cache(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_latest_cache(cache_dir: Path) -> Path | None:
    latest = cache_dir / "latest.json"
    if not latest.exists():
        return None
    meta = json.loads(latest.read_text(encoding="utf-8"))
    p = Path(meta.get("path", ""))
    return p if p.exists() else None
