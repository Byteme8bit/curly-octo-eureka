"""Tests for whale-watch detection, filtering, and state persistence."""

import json
from pathlib import Path
import time

import pandas as pd
import pytest

from bot.whale_watch import (
    WhaleEvent,
    WhaleWatcher,
    WhaleWatchState,
    detect_large_trades,
    detect_volume_spike,
    events_last_24h,
    format_whale_alert,
    prune_events,
    trade_usd_size,
)
from bot.local_time import format_pacific


def test_trade_usd_size_uses_cost():
    assert trade_usd_size({"cost": 75000, "price": 1, "amount": 1}) == pytest.approx(75000)


def test_trade_usd_size_from_price_amount():
    assert trade_usd_size({"price": 3000, "amount": 25}) == pytest.approx(75000)


def test_detect_large_trades_filters_threshold_and_dedup():
    trades = [
        {"id": "1", "side": "buy", "cost": 10000, "timestamp": 1_700_000_000_000},
        {"id": "2", "side": "sell", "cost": 80000, "price": 4000, "amount": 20, "timestamp": 1_700_000_001_000},
        {"id": "2", "side": "sell", "cost": 80000, "timestamp": 1_700_000_001_000},
    ]
    events = detect_large_trades(
        trades,
        pair="ETH/USD",
        asset="ETH",
        min_usd=50000,
        seen_ids={"2"},
    )
    assert events == []


def test_detect_large_trades_emits_event():
    trades = [
        {"id": "99", "side": "buy", "cost": 120000, "amount": 40, "price": 3000, "timestamp": 1_700_000_000_000},
    ]
    events = detect_large_trades(
        trades,
        pair="ETH/USD",
        asset="ETH",
        min_usd=50000,
        seen_ids=set(),
    )
    assert len(events) == 1
    assert events[0].asset == "ETH"
    assert events[0].direction == "buy"
    assert events[0].usd_size == pytest.approx(120000)
    assert events[0].source == "kraken_trade"


def test_detect_volume_spike():
    rows = []
    for i in range(15):
        vol = 10.0 if i < 14 else 50.0
        rows.append(
            {
                "timestamp": pd.Timestamp("2026-06-01", tz="UTC") + pd.Timedelta(minutes=5 * i),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": vol,
            }
        )
    df = pd.DataFrame(rows)
    event = detect_volume_spike(
        df,
        pair="BTC/USD",
        asset="BTC",
        min_usd=4000,
        spike_ratio=3.0,
        lookback=12,
    )
    assert event is not None
    assert event.source == "volume_spike"
    assert event.direction == "spike"
    assert event.usd_size == pytest.approx(5000.0)


def test_detect_volume_spike_below_threshold():
    rows = [{"timestamp": pd.Timestamp("2026-06-01", tz="UTC"), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1.0}] * 20
    df = pd.DataFrame(rows)
    assert detect_volume_spike(df, pair="ETH/USD", asset="ETH", min_usd=50000, spike_ratio=3.0) is None


def test_prune_events_caps_and_age():
    now = format_pacific()
    events = [{"time": now, "id": str(i)} for i in range(5)]
    pruned = prune_events(events, max_events=3, max_age_hours=168)
    assert len(pruned) == 3
    assert pruned[0]["id"] == "2"


def test_whale_state_roundtrip(tmp_path: Path):
    path = tmp_path / ".whale_watch_state.json"
    state = WhaleWatchState(last_check_at="2026-06-09 12:00:00 PDT", events=[{"id": "a"}])
    state.save(path)
    loaded = WhaleWatchState.load(path)
    assert loaded.last_check_at == state.last_check_at
    assert loaded.events == state.events


def test_whale_watcher_poll_interval_and_persistence(tmp_path: Path):
    path = tmp_path / ".whale_watch_state.json"
    calls = {"n": 0}
    now_ms = int(time.time() * 1000)

    def fetch_trades(symbol: str, limit: int) -> list[dict]:
        calls["n"] += 1
        return [
            {"id": "t1", "side": "buy", "cost": 90000, "timestamp": now_ms},
        ]

    watcher = WhaleWatcher(
        enabled=True,
        assets=("ETH",),
        min_usd=50000,
        poll_seconds=60,
        volume_spike_ratio=3.0,
        max_events=50,
        state_file=path,
        data=None,  # type: ignore[arg-type]
        fetch_trades=fetch_trades,
        fetch_candles=lambda _sym: pd.DataFrame(),
    )
    first = watcher.maybe_poll()
    assert len(first) == 1
    assert calls["n"] == 1
    second = watcher.maybe_poll()
    assert second == []
    assert calls["n"] == 1
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["last_check_at"]
    assert len(data["events"]) == 1


def test_format_whale_alert():
    event = WhaleEvent(
        id="x",
        time="t",
        asset="ETH",
        pair="ETH/USD",
        direction="buy",
        usd_size=75000,
        source="kraken_trade",
        detail="detail line",
    )
    text = format_whale_alert(event)
    assert "Whale alert" in text
    assert "ETH/USD" in text
    assert "75,000" in text


def test_events_last_24h():
    now_event = {"time": format_pacific()}
    old_event = {"time": "2020-01-01 00:00:00 PST"}
    assert events_last_24h([now_event, old_event]) == 1
