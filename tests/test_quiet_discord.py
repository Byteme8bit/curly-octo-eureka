"""Tests for Discord quiet mode, skip logs, and hourly summary helpers."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from bot.discord_summary import MajorMoveTracker, TradeActivityBuffer, format_hourly_summary
from bot.whale_follow_log import append_whale_follow_skip, read_whale_follow_skips
from bot.whale_watch import WhaleEvent
from config import load_settings


def test_quiet_mode_defaults(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_QUIET_MODE", "1")
    monkeypatch.delenv("DISCORD_HEARTBEAT_MINUTES", raising=False)
    monkeypatch.delenv("DISCORD_TRADE_SUMMARY_INTERVAL_MINUTES", raising=False)
    s = load_settings()
    assert s.discord_quiet_mode is True
    assert s.discord_heartbeat_minutes == 60
    assert s.discord_trade_summary_interval_minutes == 60
    assert s.discord_whale_skip_to_discord is False


def test_whale_follow_skip_log_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "skips.log"
    event = WhaleEvent(
        id="1",
        time="2026-06-12T12:00:00",
        asset="ETH",
        pair="ETH/USD",
        direction="buy",
        usd_size=1_500_000,
        source="kraken_trades",
        detail="",
    )
    append_whale_follow_skip(event, "fee gate", path)
    append_whale_follow_skip(event, "cooldown", path)
    lines = read_whale_follow_skips(path, last=10)
    assert len(lines) == 2
    assert "fee gate" in lines[0]
    assert "cooldown" in lines[1]


def test_activity_buffer_hourly_snapshot() -> None:
    buf = TradeActivityBuffer(window_seconds=3600)
    buf.record_trades([{"gain_loss": 2.0}])
    buf.record_trades([{"gain_loss": -1.0}])
    buf.record_blocked(["Pre-flight reject", "Pre-flight reject"])
    snap = buf.snapshot()
    assert snap["trade_count"] == 2
    assert snap["net_pnl"] == pytest.approx(1.0)
    assert snap["blocked_count"] == 2
    assert "Pre-flight" in snap["top_block_reason"]


def test_major_move_alert_once() -> None:
    tracker = MajorMoveTracker(threshold_pct=0.05, cooldown_seconds=3600)
    tracker.refresh_baselines({"ETH": 100.0})
    assert tracker.check("ETH", 100.0) is None
    alert = tracker.check("ETH", 106.0)
    assert alert is not None
    assert "ETH" in alert
    assert tracker.check("ETH", 110.0) is None


def test_format_hourly_summary_includes_tier() -> None:
    text = format_hourly_summary(
        trade_count=3,
        net_pnl=4.5,
        blocked_count=1,
        top_block_reason="edge too low",
        portfolio=10_000.0,
        baseline_pnl=25.0,
        tier_label="tier 2",
        crash_hold=True,
    )
    assert "hourly summary" in text.lower()
    assert "tier 2" in text
    assert "Crash hold" in text
