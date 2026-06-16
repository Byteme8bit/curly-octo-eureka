"""Tests for Kraken Futures paper sim and config."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bot.futures.markets import parse_futures_watchlist, resolve_watchlist_symbols
from bot.futures.paper_broker import FuturesPaperBroker


def test_parse_futures_watchlist_defaults() -> None:
    assert parse_futures_watchlist("") == ("BTC/USD:USD", "ETH/USD:USD")


def test_resolve_watchlist_symbols_filters_inactive() -> None:
    markets = {
        "BTC/USD:USD": {"active": True, "swap": True},
        "ETH/USD:USD": {"active": False, "swap": True},
        "FAKE/USD:USD": {"active": True, "swap": False},
    }
    resolved = resolve_watchlist_symbols(
        ("BTC/USD:USD", "ETH/USD:USD", "FAKE/USD:USD"), markets
    )
    assert resolved == ("BTC/USD:USD",)


def test_futures_paper_open_close(tmp_path: Path) -> None:
    broker = FuturesPaperBroker(
        tmp_path / "futures.json",
        initial_balance_usd=1000.0,
        max_leverage=5.0,
        max_position_usd=200.0,
        drawdown_halt_pct=0.50,
    )
    opened = broker.open_position(
        "BTC/USD:USD",
        "long",
        50000.0,
        leverage=5.0,
        margin_usd=50.0,
        reason="test",
    )
    assert opened is not None
    assert "BTC/USD:USD" in broker.state.positions
    closed = broker.close_position("BTC/USD:USD", 51000.0, reason="take profit")
    assert closed is not None
    assert "BTC/USD:USD" not in broker.state.positions
    assert broker.state.balance_usd > 900.0


def test_futures_drawdown_halt(tmp_path: Path) -> None:
    broker = FuturesPaperBroker(
        tmp_path / "futures.json",
        initial_balance_usd=1000.0,
        max_leverage=2.0,
        max_position_usd=500.0,
        drawdown_halt_pct=0.05,
    )
    broker.open_position(
        "ETH/USD:USD",
        "long",
        3000.0,
        leverage=2.0,
        margin_usd=200.0,
        reason="test",
    )
    broker.mark_to_market({"ETH/USD:USD": 1500.0})
    assert broker.state.halted
    assert "drawdown" in broker.state.halt_reason.lower()


def test_settings_futures_fields(monkeypatch) -> None:
    from config import load_settings

    monkeypatch.setenv("ENABLE_FUTURES", "1")
    monkeypatch.setenv("FUTURES_WATCHLIST", "BTC/USD:USD")
    monkeypatch.setenv("FUTURES_MAX_LEVERAGE", "3")
    with patch("bot.futures.manager.FuturesManager.__init__", return_value=None):
        settings = load_settings()
    assert settings.enable_futures is True
    assert settings.futures_watchlist == ("BTC/USD:USD",)
    assert settings.futures_max_leverage == 3.0


def test_futures_manager_paper_tick(tmp_path: Path, monkeypatch) -> None:
    from bot.futures.manager import FuturesManager
    from config import load_settings

    monkeypatch.setenv("ENABLE_FUTURES", "1")
    monkeypatch.setenv("FUTURES_WATCHLIST", "BTC/USD:USD")
    monkeypatch.setenv("FUTURES_PAPER_STATE_FILE", str(tmp_path / "fp.json"))
    settings = load_settings()

    mock_exchange = MagicMock()
    mock_exchange.load_markets.return_value = {
        "BTC/USD:USD": {"active": True, "swap": True, "limits": {"leverage": {"max": 10}}},
    }
    mock_exchange.market.return_value = {
        "limits": {"leverage": {"max": 10}},
    }
    mock_exchange.fetch_tickers.return_value = {
        "BTC/USD:USD": {"last": 50000.0},
    }

    with patch(
        "bot.futures.manager.build_futures_exchange", return_value=mock_exchange
    ):
        mgr = FuturesManager(settings)
    assert mgr.active
    trades = mgr.tick()
    assert trades == []
    mock_exchange.fetch_tickers.return_value = {
        "BTC/USD:USD": {"last": 50200.0},
    }
    trades = mgr.tick()
    assert len(trades) == 1
    assert trades[0]["action"] == "open"
