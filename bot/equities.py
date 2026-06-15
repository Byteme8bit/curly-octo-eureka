"""Kraken xStocks (tokenized equities/ETFs) on spot — separate asset class from crypto."""

from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

KRAKEN_PUBLIC_API = "https://api.kraken.com/0/public"
TOKENIZED_ASSET_CLASS = "tokenized_asset"
DEFAULT_EQUITY_WATCHLIST = ("AAPLx", "TSLAx", "SPYx")


def parse_equity_watchlist(raw: str) -> tuple[str, ...]:
    assets = tuple(a.strip() for a in raw.split(",") if a.strip())
    return assets or DEFAULT_EQUITY_WATCHLIST


def equity_usd_symbol(asset: str) -> str:
    return f"{asset}/USD"


def kraken_pair_id(symbol: str) -> str:
    """CCXT-style ``AAPLx/USD`` → Kraken REST ``AAPLxUSD``."""
    base, quote = symbol.split("/", 1)
    return f"{base}{quote}"


def is_equity_asset(asset: str, equity_assets: frozenset[str]) -> bool:
    return asset in equity_assets


def is_equity_symbol(symbol: str, equity_assets: frozenset[str]) -> bool:
    if "/" not in symbol:
        return False
    return symbol.split("/", 1)[0] in equity_assets


def fetch_tokenized_pairs(
    *,
    session: requests.Session | None = None,
    timeout: float = 30.0,
) -> dict[str, dict[str, Any]]:
    """Load tradable xStock pairs (``aclass_base=tokenized_asset``)."""
    http = session or requests
    resp = http.get(
        f"{KRAKEN_PUBLIC_API}/AssetPairs",
        params={"aclass_base": TOKENIZED_ASSET_CLASS},
        timeout=timeout,
    )
    resp.raise_for_status()
    payload = resp.json()
    errors = payload.get("error") or []
    if errors:
        raise RuntimeError(f"Kraken AssetPairs error: {errors}")
    result = payload.get("result") or {}
    if not isinstance(result, dict):
        return {}
    return result


def resolve_watchlist_pairs(
    watchlist: tuple[str, ...],
    pairs: dict[str, dict[str, Any]] | None = None,
) -> tuple[str, ...]:
    """Return USD symbols present on Kraken for the requested watchlist."""
    catalog = pairs if pairs is not None else fetch_tokenized_pairs()
    by_wsname: dict[str, dict[str, Any]] = {}
    by_base: dict[str, dict[str, Any]] = {}
    for info in catalog.values():
        ws = str(info.get("wsname") or "")
        base = str(info.get("base") or "")
        if ws:
            by_wsname[ws.upper()] = info
        if base:
            by_base[base.upper()] = info

    resolved: list[str] = []
    missing: list[str] = []
    for asset in watchlist:
        symbol = equity_usd_symbol(asset)
        info = by_wsname.get(symbol.upper()) or by_base.get(asset.upper())
        if info and str(info.get("status", "online")) == "online":
            ws = str(info.get("wsname") or symbol)
            if ws not in resolved:
                resolved.append(ws)
        else:
            missing.append(asset)
    if missing:
        logger.warning(
            "Equity watchlist assets not found or offline on Kraken: %s",
            ", ".join(missing),
        )
    return tuple(resolved)


def inject_equity_markets(
    exchange,
    pairs: dict[str, dict[str, Any]],
    equity_symbols: tuple[str, ...],
) -> None:
    """Merge tokenized-asset metadata into a ccxt Kraken ``markets`` map."""
    if not hasattr(exchange, "markets") or exchange.markets is None:
        exchange.markets = {}
    markets_by_id = getattr(exchange, "markets_by_id", None)
    if markets_by_id is None:
        markets_by_id = {}
        exchange.markets_by_id = markets_by_id

    by_ws: dict[str, dict[str, Any]] = {}
    for pair_id, info in pairs.items():
        ws = str(info.get("wsname") or "")
        if ws:
            by_ws[ws.upper()] = {**info, "_pair_id": pair_id}

    for symbol in equity_symbols:
        info = by_ws.get(symbol.upper())
        if not info:
            continue
        base = str(info.get("base") or symbol.split("/")[0])
        quote = "USD"
        pair_id = str(info.get("_pair_id") or kraken_pair_id(symbol))
        lot_dec = int(info.get("lot_decimals", 5) or 5)
        pair_dec = int(info.get("pair_decimals", 5) or 5)
        ordermin = info.get("ordermin")
        min_amt = float(ordermin) if ordermin not in (None, "") else None
        fees = info.get("fees") or []
        taker = float(fees[0][1]) / 100.0 if fees else None
        market = {
            "id": pair_id,
            "symbol": symbol,
            "base": base,
            "quote": quote,
            "baseId": base,
            "quoteId": "ZUSD",
            "active": str(info.get("status", "online")) == "online",
            "type": "spot",
            "spot": True,
            "margin": False,
            "swap": False,
            "future": False,
            "contract": False,
            "precision": {"amount": lot_dec, "price": pair_dec},
            "limits": {
                "amount": {"min": min_amt, "max": None},
                "price": {"min": None, "max": None},
                "cost": {"min": None, "max": None},
            },
            "info": info,
            "taker": taker,
            "maker": taker,
        }
        exchange.markets[symbol] = market
        markets_by_id[pair_id] = market


def fetch_equity_ticker(
    symbol: str,
    *,
    session: requests.Session | None = None,
    timeout: float = 30.0,
) -> float:
    http = session or requests
    pair = kraken_pair_id(symbol)
    resp = http.get(
        f"{KRAKEN_PUBLIC_API}/Ticker",
        params={"pair": pair, "asset_class": TOKENIZED_ASSET_CLASS},
        timeout=timeout,
    )
    resp.raise_for_status()
    payload = resp.json()
    errors = payload.get("error") or []
    if errors:
        raise RuntimeError(f"Kraken Ticker error for {symbol}: {errors}")
    result = payload.get("result") or {}
    row = result.get(pair) or next(iter(result.values()), None)
    if not row:
        raise RuntimeError(f"Kraken Ticker empty for {symbol}")
    last = row.get("c", [None])[0]
    return float(last)


def fetch_equity_ohlcv(
    symbol: str,
    *,
    timeframe: str = "5m",
    limit: int = 60,
    session: requests.Session | None = None,
    timeout: float = 30.0,
) -> list[list[float]]:
    """Return ccxt-style OHLCV rows ``[ts, o, h, l, c, v]``."""
    interval = _timeframe_minutes(timeframe)
    http = session or requests
    pair = kraken_pair_id(symbol)
    resp = http.get(
        f"{KRAKEN_PUBLIC_API}/OHLC",
        params={
            "pair": pair,
            "interval": interval,
            "asset_class": TOKENIZED_ASSET_CLASS,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    payload = resp.json()
    errors = payload.get("error") or []
    if errors:
        raise RuntimeError(f"Kraken OHLC error for {symbol}: {errors}")
    result = payload.get("result") or {}
    rows = result.get(pair) or []
    if not rows and result:
        for key, val in result.items():
            if key != "last" and isinstance(val, list):
                rows = val
                break
    out: list[list[float]] = []
    for row in rows[-limit:]:
        if len(row) < 7:
            continue
        ts_ms = int(row[0]) * 1000
        out.append([ts_ms, float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])])
    return out


def _timeframe_minutes(timeframe: str) -> int:
    mapping = {
        "1m": 1,
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "1h": 60,
        "4h": 240,
        "1d": 1440,
    }
    return mapping.get(timeframe, 5)
