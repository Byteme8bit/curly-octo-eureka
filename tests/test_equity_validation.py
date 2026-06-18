"""Startup equity watchlist validation against Kraken AssetPairs."""

from __future__ import annotations

from unittest.mock import patch

from bot.equities import filter_equity_watchlist


def _mock_pair(base: str) -> dict:
    return {
        "base": base,
        "quote": "ZUSD",
        "wsname": f"{base}/USD",
        "status": "online",
        "lot_decimals": 5,
        "pair_decimals": 2,
        "ordermin": "0.01",
        "fees": [["0", "40"]],
    }


def test_filter_equity_watchlist_returns_skipped() -> None:
    catalog = {
        "AAPLxUSD": _mock_pair("AAPLx"),
        "SPYxUSD": _mock_pair("SPYx"),
    }
    valid, skipped, symbols = filter_equity_watchlist(
        ("AAPLx", "TSLAx", "SPYx"), catalog
    )
    assert valid == ("AAPLx", "SPYx")
    assert skipped == ("TSLAx",)
    assert symbols == ("AAPLx/USD", "SPYx/USD")


def test_load_settings_strips_missing_equities_from_live_allowlist(monkeypatch) -> None:
    from config import load_settings

    monkeypatch.setenv("ENABLE_EQUITIES", "1")
    monkeypatch.setenv("EQUITY_WATCHLIST", "AAPLx,TSLAx,SPYx")
    monkeypatch.setenv("EQUITY_PREFERENCE_TICKERS", "")
    monkeypatch.setenv("LIVE_EQUITY_AUTO_ALLOW", "0")
    monkeypatch.setenv("LIVE_ALLOWED_ASSETS", "ETH,BTC,TSLAx,SPYx,AAPLx")
    catalog = {
        "AAPLxUSD": _mock_pair("AAPLx"),
        "SPYxUSD": _mock_pair("SPYx"),
    }
    with patch("bot.equities.fetch_tokenized_pairs", return_value=catalog):
        settings = load_settings()
    assert "TSLAx" not in settings.equity_watchlist
    assert "TSLAx" not in settings.live_allowed_assets
    assert "AAPLx" in settings.live_allowed_assets
    assert "SPYx" in settings.live_allowed_assets
    assert "BTC" in settings.live_allowed_assets


def test_load_settings_all_equity_watchlist_mode(monkeypatch) -> None:
    from config import load_settings

    monkeypatch.setenv("ENABLE_EQUITIES", "1")
    monkeypatch.setenv("EQUITY_WATCHLIST_MODE", "all")
    monkeypatch.setenv("EQUITY_PREFERENCE_TICKERS", "")
    monkeypatch.setenv("LIVE_EQUITY_AUTO_ALLOW", "0")
    catalog = {
        "AAPLxUSD": _mock_pair("AAPLx"),
        "NVDAxUSD": _mock_pair("NVDAx"),
        "AMDxUSD": _mock_pair("AMDx"),
    }
    with patch("bot.equities.fetch_tokenized_pairs", return_value=catalog):
        settings = load_settings()
    assert settings.equity_watchlist == ("AAPLx", "AMDx", "NVDAx")
    assert len(settings.equity_usd_symbols) == 3


def test_load_settings_live_equity_auto_allow(monkeypatch) -> None:
    from config import load_settings

    monkeypatch.setenv("ENABLE_EQUITIES", "1")
    monkeypatch.setenv("EQUITY_WATCHLIST", "AAPLx,NVDAx")
    monkeypatch.setenv("EQUITY_PREFERENCE_TICKERS", "")
    monkeypatch.setenv("LIVE_ALLOWED_ASSETS", "ETH,BTC")
    monkeypatch.setenv("LIVE_EQUITY_AUTO_ALLOW", "1")
    catalog = {
        "AAPLxUSD": _mock_pair("AAPLx"),
        "NVDAxUSD": _mock_pair("NVDAx"),
    }
    with patch("bot.equities.fetch_tokenized_pairs", return_value=catalog):
        settings = load_settings()
    assert "AAPLx" in settings.live_allowed_assets
    assert "NVDAx" in settings.live_allowed_assets
    assert "ETH" in settings.live_allowed_assets


def test_max_equity_positions_blocks_new_ticker() -> None:
    from bot.portfolio_constraints import PortfolioConstraints
    from bot.strategies.base import TradeIntent

    constraints = PortfolioConstraints(
        min_eth_reserve=0.25,
        max_alt_allocation_pct=0.40,
        min_usd_trade=10.0,
        equity_assets=frozenset({"AAPLx", "TSLAx", "NVDAx"}),
        max_equity_allocation_pct=0.25,
        max_equity_positions=2,
        dust_usd=5.0,
    )
    intent = TradeIntent(
        from_asset="USD",
        to_asset="NVDAx",
        reason="test",
        size_pct=0.1,
        edge=0.01,
    )
    holdings = {"USD": 1000.0, "AAPLx": 1.0, "TSLAx": 1.0}
    prices = {"USD": 1.0, "AAPLx": 200.0, "TSLAx": 300.0, "NVDAx": 150.0}
    result = constraints.validate_intent(intent, holdings, prices, required_edge=0.005)
    assert not result.allowed
    assert "Equity positions" in result.reason
