"""Tests for Kraken xStock (tokenized equity) support."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from bot.equities import (
    inject_equity_markets,
    is_equity_asset,
    is_equity_symbol,
    kraken_pair_id,
    resolve_watchlist_pairs,
)
from bot.live_guards import check_live_route
from bot.markets import MarketRegistry, PairInfo, RouteLeg, TradeRoute
from bot.portfolio_constraints import PortfolioConstraints
from bot.strategies.base import Signal


def _mock_pair(base: str, ws: str | None = None) -> dict:
    symbol = ws or f"{base}/USD"
    return {
        "base": base,
        "quote": "ZUSD",
        "wsname": symbol,
        "status": "online",
        "lot_decimals": 5,
        "pair_decimals": 2,
        "ordermin": "0.01",
        "fees": [["0", "40"]],
    }


def test_kraken_pair_id_normalizes_slash_symbols() -> None:
    assert kraken_pair_id("AAPLx/USD") == "AAPLxUSD"
    assert kraken_pair_id("BRK.Bx/USD") == "BRK.BxUSD"


def test_resolve_watchlist_pairs_filters_missing() -> None:
    catalog = {
        "AAPLxUSD": _mock_pair("AAPLx"),
        "TSLAxUSD": _mock_pair("TSLAx"),
    }
    resolved = resolve_watchlist_pairs(("AAPLx", "TSLAx", "FAKEx"), catalog)
    assert resolved == ("AAPLx/USD", "TSLAx/USD")


def test_inject_equity_markets_adds_ccxt_entries() -> None:
    exchange = MagicMock()
    exchange.markets = {}
    exchange.markets_by_id = {}
    catalog = {"AAPLxUSD": _mock_pair("AAPLx")}
    inject_equity_markets(exchange, catalog, ("AAPLx/USD",))
    assert "AAPLx/USD" in exchange.markets
    assert exchange.markets["AAPLx/USD"]["base"] == "AAPLx"
    assert exchange.markets["AAPLx/USD"]["taker"] == pytest.approx(0.4)


def test_market_registry_equity_usd_only() -> None:
    exchange = MagicMock()
    exchange.load_markets.return_value = {
        "ETH/USD": {"active": True, "base": "ETH", "quote": "USD"},
        "AAPLx/USD": {"active": True, "base": "AAPLx", "quote": "USD"},
        "AAPLx/ETH": {"active": True, "base": "AAPLx", "quote": "ETH"},
    }
    reg = MarketRegistry(
        exchange,
        ("ETH", "AAPLx"),
        equity_assets=frozenset({"AAPLx"}),
    )
    assert reg.symbol_exists("AAPLx/USD")
    assert not reg.symbol_exists("AAPLx/ETH")


def test_live_route_allows_equity_when_in_allowlist() -> None:
    route = TradeRoute(
        legs=(
            RouteLeg(
                pair=PairInfo("AAPLx/USD", "AAPLx", "USD"),
                side=Signal.BUY,
                from_asset="USD",
                to_asset="AAPLx",
            ),
        )
    )
    ok, reason = check_live_route(route, ("ETH", "ADA", "AAPLx"))
    assert ok, reason


def test_live_route_blocks_equity_not_in_allowlist() -> None:
    route = TradeRoute(
        legs=(
            RouteLeg(
                pair=PairInfo("TSLAx/USD", "TSLAx", "USD"),
                side=Signal.BUY,
                from_asset="USD",
                to_asset="TSLAx",
            ),
        )
    )
    ok, reason = check_live_route(route, ("ETH", "ADA"))
    assert not ok
    assert "TSLAx" in reason


def test_portfolio_constraints_equity_cap() -> None:
    constraints = PortfolioConstraints(
        min_eth_reserve=0.25,
        max_alt_allocation_pct=0.40,
        min_usd_trade=10.0,
        equity_assets=frozenset({"AAPLx"}),
        max_equity_allocation_pct=0.15,
    )
    from bot.strategies.base import TradeIntent

    intent = TradeIntent(
        from_asset="USD",
        to_asset="AAPLx",
        reason="test equity buy",
        size_pct=0.5,
        edge=0.01,
    )
    holdings = {"USD": 1000.0, "ETH": 1.0}
    prices = {"USD": 1.0, "ETH": 3000.0, "AAPLx": 300.0}
    result = constraints.validate_intent(intent, holdings, prices, required_edge=0.005)
    assert result.allowed, result.reason


def test_filter_equity_watchlist_splits_valid_and_skipped() -> None:
    from bot.equities import filter_equity_watchlist

    catalog = {
        "AAPLxUSD": _mock_pair("AAPLx"),
        "TSLAxUSD": _mock_pair("TSLAx"),
    }
    valid, skipped, symbols = filter_equity_watchlist(
        ("AAPLx", "TSLAx", "FAKEx"), catalog
    )
    assert valid == ("AAPLx", "TSLAx")
    assert skipped == ("FAKEx",)
    assert symbols == ("AAPLx/USD", "TSLAx/USD")


def test_settings_include_equity_symbols_when_enabled(monkeypatch) -> None:
    from config import load_settings

    monkeypatch.setenv("ENABLE_EQUITIES", "1")
    monkeypatch.setenv("EQUITY_WATCHLIST", "AAPLx,TSLAx")
    with patch(
        "bot.equities.resolve_watchlist_pairs",
        return_value=("AAPLx/USD", "TSLAx/USD"),
    ):
        settings = load_settings()
    assert settings.enable_equities is True
    assert "AAPLx/USD" in settings.usd_symbols
    assert settings.symbol_assets["AAPLx/USD"] == "AAPLx"
    assert is_equity_asset("AAPLx", settings.equity_assets)
    assert is_equity_symbol("AAPLx/USD", settings.equity_assets)
