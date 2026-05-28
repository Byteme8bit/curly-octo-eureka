"""Tests for watchdog state: error categorization + wall-clock timestamps (feature 006)."""
from __future__ import annotations

import json
import time

from watchdog.state import WALL_CLOCK_MIN, WatchdogState


def test_record_error_bot_vs_watchdog():
    state = WatchdogState()
    state.record_error(source="bot")
    state.record_error(source="bot")
    state.record_error(source="watchdog")

    assert len(state.error_timestamps) == 2
    assert len(state.watchdog_error_timestamps) == 1


def test_timestamps_are_wall_clock():
    state = WatchdogState()
    state.record_error()
    ts = state.error_timestamps[0]
    assert ts > WALL_CLOCK_MIN
    assert abs(ts - time.time()) < 5


def test_track_error_for_pin_threshold():
    state = WatchdogState()
    # 1st, 2nd, 3rd: not yet pinned (need MORE than 3)
    for _ in range(3):
        assert not state.track_error_for_pin("err-A", window_sec=1800, threshold=3)
    # 4th: now > 3 in window
    assert state.track_error_for_pin("err-A", window_sec=1800, threshold=3)


def test_track_error_for_pin_window_expiry():
    state = WatchdogState()
    # Seed with 5 ancient occurrences (outside 30-min window)
    state.error_pin_windows["err-B"] = [time.time() - 3600 for _ in range(5)]
    # Next occurrence should NOT trigger because the old ones are pruned
    assert not state.track_error_for_pin("err-B", window_sec=1800, threshold=3)


def test_should_alert_error_cooldown():
    state = WatchdogState()
    assert state.should_alert_error("k1", cooldown_sec=300)
    # Same key within cooldown -> suppressed
    assert not state.should_alert_error("k1", cooldown_sec=300)


def test_load_strips_monotonic_timestamps(tmp_path):
    """Old state files with monotonic timestamps should be cleaned on load."""
    path = tmp_path / ".watchdog_state.json"
    stale_monotonic = 1234.5  # below year-2001 epoch — clearly monotonic
    path.write_text(
        json.dumps({
            "error_timestamps": [stale_monotonic],
            "watchdog_error_timestamps": [stale_monotonic],
            "last_heartbeat_at": stale_monotonic,
            "error_pin_windows": {"err": [stale_monotonic]},
            "seen_error_keys": {"err": stale_monotonic},
        }),
        encoding="utf-8",
    )
    state = WatchdogState.load(path)
    assert state.error_timestamps == []
    assert state.watchdog_error_timestamps == []
    assert state.last_heartbeat_at == 0.0
    assert state.error_pin_windows == {}
    assert state.seen_error_keys == {}


def test_load_keeps_valid_wallclock_timestamps(tmp_path):
    path = tmp_path / ".watchdog_state.json"
    now = time.time()
    path.write_text(
        json.dumps({
            "error_timestamps": [now - 60],
            "watchdog_error_timestamps": [now - 30],
        }),
        encoding="utf-8",
    )
    state = WatchdogState.load(path)
    assert len(state.error_timestamps) == 1
    assert len(state.watchdog_error_timestamps) == 1


def test_reset_session_clears_both_buckets():
    state = WatchdogState()
    state.record_error(source="bot")
    state.record_error(source="watchdog")
    state.reset_session()
    assert state.error_timestamps == []
    assert state.watchdog_error_timestamps == []
