"""Kraken Futures market catalog via ccxt.krakenfutures."""

from __future__ import annotations

import logging
from typing import Any

import ccxt

logger = logging.getLogger(__name__)

DEFAULT_FUTURES_WATCHLIST = ("BTC/USD:USD", "ETH/USD:USD")


def parse_futures_watchlist(raw: str) -> tuple[str, ...]:
    symbols = tuple(s.strip() for s in raw.split(",") if s.strip())
    return symbols or DEFAULT_FUTURES_WATCHLIST


def build_futures_exchange(
    *,
    api_key: str = "",
    api_secret: str = "",
    timeout_ms: int = 5000,
) -> ccxt.krakenfutures:
    config: dict[str, Any] = {
        "enableRateLimit": True,
        "timeout": timeout_ms,
    }
    if api_key and api_secret:
        config["apiKey"] = api_key
        config["secret"] = api_secret
    return ccxt.krakenfutures(config)


def resolve_watchlist_symbols(
    watchlist: tuple[str, ...],
    markets: dict[str, dict[str, Any]] | None = None,
    *,
    exchange: ccxt.krakenfutures | None = None,
) -> tuple[str, ...]:
    """Return ccxt swap symbols that exist and are active."""
    catalog = markets
    if catalog is None:
        if exchange is None:
            exchange = build_futures_exchange()
        catalog = exchange.load_markets()
    resolved: list[str] = []
    missing: list[str] = []
    for symbol in watchlist:
        info = catalog.get(symbol)
        if info and info.get("active", True) and info.get("swap"):
            if symbol not in resolved:
                resolved.append(symbol)
        else:
            missing.append(symbol)
    if missing:
        logger.warning(
            "Futures watchlist symbols not found or inactive: %s",
            ", ".join(missing),
        )
    return tuple(resolved)


def symbol_leverage_cap(market: dict[str, Any], max_leverage: float) -> float:
    """Effective leverage cap = min(config max, exchange max)."""
    limits = market.get("limits") or {}
    lev = limits.get("leverage") or {}
    exchange_max = lev.get("max")
    if exchange_max is not None:
        try:
            return min(max_leverage, float(exchange_max))
        except (TypeError, ValueError):
            pass
    return max_leverage
