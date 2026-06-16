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
