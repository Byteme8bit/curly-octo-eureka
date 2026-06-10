"""Whale watch Discord gating and quiet file log."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bot.whale_watch import WhaleEvent, append_whale_event_log, format_whale_log_line
from config import load_settings


def _sample_event() -> WhaleEvent:
    return WhaleEvent(
        id="t1",
        time="2026-06-10T12:00:00+00:00",
        asset="ETH",
        pair="ETH/USD",
        direction="buy",
        usd_size=75000.0,
        source="large_trade",
        detail="Kraken public trade",
    )


def test_whale_watch_discord_alerts_default_off(monkeypatch):
    monkeypatch.delenv("WHALE_WATCH_DISCORD_ALERTS", raising=False)
    settings = load_settings()
    assert settings.whale_watch_discord_alerts is False


def test_whale_watch_discord_alerts_enabled_from_env(monkeypatch):
    monkeypatch.setenv("WHALE_WATCH_DISCORD_ALERTS", "1")
    settings = load_settings()
    assert settings.whale_watch_discord_alerts is True


def test_append_whale_event_log_writes_line(tmp_path: Path):
    path = tmp_path / "whale_watch.log"
    event = _sample_event()
    append_whale_event_log(event, path)
    text = path.read_text(encoding="utf-8")
    assert format_whale_log_line(event) in text


def test_maybe_whale_watch_skips_discord_when_alerts_disabled():
    from bot.engine import TradingEngine

    event = _sample_event()
    engine = MagicMock(spec=TradingEngine)
    engine.settings = MagicMock(
        whale_watch_enabled=True,
        discord_enabled=True,
        whale_watch_discord_alerts=False,
        whale_watch_log_file=Path("logs/whale_watch.log"),
        whale_follow_enabled=False,
    )
    engine.whale_watcher = MagicMock()
    engine.whale_watcher.maybe_poll.return_value = [event]
    engine.discord = MagicMock()

    with patch("bot.engine.append_whale_event_log") as log_mock:
        TradingEngine._maybe_whale_watch(engine)

    log_mock.assert_called_once_with(event, engine.settings.whale_watch_log_file)
    engine.discord.post_important.assert_not_called()


def test_maybe_whale_watch_posts_discord_when_alerts_enabled():
    from bot.engine import TradingEngine

    event = _sample_event()
    engine = MagicMock(spec=TradingEngine)
    engine.settings = MagicMock(
        whale_watch_enabled=True,
        discord_enabled=True,
        whale_watch_discord_alerts=True,
        whale_watch_log_file=Path("logs/whale_watch.log"),
        whale_follow_enabled=False,
    )
    engine.whale_watcher = MagicMock()
    engine.whale_watcher.maybe_poll.return_value = [event]
    engine.discord = MagicMock()

    with patch("bot.engine.append_whale_event_log"):
        TradingEngine._maybe_whale_watch(engine)

    engine.discord.post_important.assert_called_once()
    args, kwargs = engine.discord.post_important.call_args
    assert "Whale alert" in args[0]
    assert kwargs.get("source") == "TradeBot"
