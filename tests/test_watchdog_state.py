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


def test_reset_process_session_counters_clears_trades_not_errors():
    """Regression: per-process counters used to accumulate across restarts,
    pinning health score at 90/100 forever once trades_session > 40.

    The per-process reset is called from begin_session() and should ONLY
    touch counters whose name implies per-process scope. Error history
    and dedup state must persist so a crash-loop bot stays scored low."""
    state = WatchdogState()
    state.trades_session = 114          # the user's actual observed value
    state.watchdog_pause_count = 3
    state.last_watchdog_pause_at = "2026-05-30 04:00:00 PDT"
    state.record_error(source="bot")
    state.record_error(source="watchdog")
    state.seen_error_keys["err-A"] = time.time()
    state.last_pnl_band = 5

    state.reset_process_session_counters()

    # Cleared (per-process scope)
    assert state.trades_session == 0
    assert state.watchdog_pause_count == 0
    assert state.last_watchdog_pause_at is None

    # Preserved (cross-restart scope)
    assert len(state.error_timestamps) == 1
    assert len(state.watchdog_error_timestamps) == 1
    assert "err-A" in state.seen_error_keys
    assert state.last_pnl_band == 5


def test_append_error_stamps_ts():
    """append_error() must inject a ``_ts`` unix-timestamp into every record."""
    state = WatchdogState()
    state.append_error({"at": "2026-06-01 00:00:00 PDT", "level": "ERROR", "message": "boom"})
    assert len(state.recent_errors) == 1
    record = state.recent_errors[0]
    assert "_ts" in record
    assert record["_ts"] > WALL_CLOCK_MIN
    assert abs(record["_ts"] - time.time()) < 5


def test_append_error_preserves_existing_ts():
    """If the caller already provided ``_ts``, it must not be overwritten."""
    state = WatchdogState()
    explicit_ts = time.time() - 100
    state.append_error({"at": "old", "level": "ERROR", "message": "x", "_ts": explicit_ts})
    assert abs(state.recent_errors[0]["_ts"] - explicit_ts) < 1e-6


def test_load_prunes_stale_recent_errors(tmp_path):
    """WatchdogState.load() must drop recent_errors entries older than 24 hours."""
    path = tmp_path / ".watchdog_state.json"
    old_ts = time.time() - 90000  # 25 hours ago
    fresh_ts = time.time() - 60   # 1 minute ago
    path.write_text(
        json.dumps({
            "recent_errors": [
                {"at": "stale", "level": "ERROR", "message": "old-error", "_ts": old_ts},
                {"at": "fresh", "level": "ERROR", "message": "new-error", "_ts": fresh_ts},
            ]
        }),
        encoding="utf-8",
    )
    state = WatchdogState.load(path)
    assert len(state.recent_errors) == 1
    assert state.recent_errors[0]["message"] == "new-error"


def test_load_keeps_recent_errors_without_ts(tmp_path):
    """Records from older builds (no ``_ts``) are kept for backward compatibility."""
    path = tmp_path / ".watchdog_state.json"
    path.write_text(
        json.dumps({
            "recent_errors": [
                {"at": "legacy", "level": "ERROR", "message": "no-ts-entry"},
            ]
        }),
        encoding="utf-8",
    )
    state = WatchdogState.load(path)
    assert len(state.recent_errors) == 1
    assert state.recent_errors[0]["message"] == "no-ts-entry"
