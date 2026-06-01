"""Regression tests: stale TTL-based fields are pruned on state load.

Mirrors the auditor-state pattern from feature 019/PR #8: expired TTL entries
should be removed eagerly at load time rather than lazily on first gate check.

Covers three state files:
  .paper_state.json  — RiskState.from_dict() pruning (new, this PR)
  .watchdog_state.json — WatchdogState.load() pruning (existing behaviour)
  .discord_pins.json — PinTracker._load() has no TTL fields; channel-ID guard.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from bot.paper_broker import RiskState
from watchdog.state import WALL_CLOCK_MIN, WatchdogState


# ---------------------------------------------------------------------------
# RiskState — paused_until pruning
# ---------------------------------------------------------------------------

class TestRiskStatePrunedPausedUntil:
    def test_expired_paused_until_is_cleared(self):
        past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        state = RiskState.from_dict({"paused_until": past, "hibernate_alert_sent": True})
        assert state.paused_until is None
        assert state.hibernate_alert_sent is False

    def test_future_paused_until_is_preserved(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        state = RiskState.from_dict({"paused_until": future, "hibernate_alert_sent": True})
        assert state.paused_until == future
        assert state.hibernate_alert_sent is True

    def test_none_paused_until_is_a_noop(self):
        state = RiskState.from_dict({"paused_until": None})
        assert state.paused_until is None

    def test_unparseable_paused_until_is_cleared(self):
        state = RiskState.from_dict({"paused_until": "not-a-date", "hibernate_alert_sent": True})
        assert state.paused_until is None
        assert state.hibernate_alert_sent is False


# ---------------------------------------------------------------------------
# RiskState — trades_this_hour / hour_window_start pruning
# ---------------------------------------------------------------------------

class TestRiskStateHourWindowPruning:
    def test_expired_hour_window_resets_trade_count(self):
        old_window = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        state = RiskState.from_dict({
            "hour_window_start": old_window,
            "trades_this_hour": 7,
        })
        assert state.trades_this_hour == 0
        assert state.hour_window_start is None

    def test_recent_hour_window_preserves_trade_count(self):
        recent_window = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        state = RiskState.from_dict({
            "hour_window_start": recent_window,
            "trades_this_hour": 3,
        })
        assert state.trades_this_hour == 3
        assert state.hour_window_start == recent_window

    def test_none_hour_window_is_a_noop(self):
        state = RiskState.from_dict({"hour_window_start": None, "trades_this_hour": 0})
        assert state.trades_this_hour == 0

    def test_unparseable_hour_window_resets_trade_count(self):
        state = RiskState.from_dict({
            "hour_window_start": "garbage",
            "trades_this_hour": 4,
        })
        assert state.trades_this_hour == 0
        assert state.hour_window_start is None

    def test_exactly_at_boundary_is_pruned(self):
        """A window exactly 3600 s old (>= threshold) is also pruned."""
        exactly_one_hour_ago = (
            datetime.now(timezone.utc) - timedelta(seconds=3600)
        ).isoformat()
        state = RiskState.from_dict({
            "hour_window_start": exactly_one_hour_ago,
            "trades_this_hour": 5,
        })
        assert state.trades_this_hour == 0


# ---------------------------------------------------------------------------
# WatchdogState — existing load-time TTL pruning (regression guard)
# ---------------------------------------------------------------------------

class TestWatchdogStateStaleLoad:
    def test_stale_seen_error_keys_dropped(self, tmp_path):
        path = tmp_path / ".watchdog_state.json"
        stale_ts = time.time() - (25 * 3600)  # 25 h ago — past 24 h max_age
        path.write_text(
            json.dumps({"seen_error_keys": {"old-key": stale_ts}}),
            encoding="utf-8",
        )
        state = WatchdogState.load(path)
        assert "old-key" not in state.seen_error_keys

    def test_fresh_seen_error_keys_kept(self, tmp_path):
        path = tmp_path / ".watchdog_state.json"
        fresh_ts = time.time() - 300  # 5 min ago — within 24 h max_age
        path.write_text(
            json.dumps({"seen_error_keys": {"fresh-key": fresh_ts}}),
            encoding="utf-8",
        )
        state = WatchdogState.load(path)
        assert "fresh-key" in state.seen_error_keys

    def test_stale_error_timestamps_dropped(self, tmp_path):
        path = tmp_path / ".watchdog_state.json"
        stale_ts = time.time() - (25 * 3600)
        path.write_text(
            json.dumps({"error_timestamps": [stale_ts]}),
            encoding="utf-8",
        )
        state = WatchdogState.load(path)
        assert state.error_timestamps == []

    def test_monotonic_heartbeat_cleared(self, tmp_path):
        """Sub-WALL_CLOCK_MIN heartbeat from an old build is replaced with 0."""
        path = tmp_path / ".watchdog_state.json"
        path.write_text(
            json.dumps({"last_heartbeat_at": 12345.0}),  # monotonic, not epoch
            encoding="utf-8",
        )
        state = WatchdogState.load(path)
        assert state.last_heartbeat_at == 0.0


# ---------------------------------------------------------------------------
# PinTracker — channel_id guard (no TTL fields, but load discards wrong-channel data)
# ---------------------------------------------------------------------------

class TestPinTrackerChannelGuard:
    def test_mismatched_channel_id_discards_pins(self, tmp_path):
        from bot.pin_tracker import PinTracker

        state_file = tmp_path / ".discord_pins.json"
        state_file.write_text(
            json.dumps({
                "channel_id": "wrong-channel",
                "pinned_message_ids": ["111", "222"],
                "startup_pin_message_id": "999",
            }),
            encoding="utf-8",
        )
        tracker = PinTracker(state_file, channel_id="correct-channel", max_retain=10)
        assert tracker.ids() == []
        assert tracker.startup_pin_id() is None

    def test_matching_channel_id_loads_pins(self, tmp_path):
        from bot.pin_tracker import PinTracker

        state_file = tmp_path / ".discord_pins.json"
        state_file.write_text(
            json.dumps({
                "channel_id": "my-channel",
                "pinned_message_ids": ["111", "222"],
                "startup_pin_message_id": "999",
            }),
            encoding="utf-8",
        )
        tracker = PinTracker(state_file, channel_id="my-channel", max_retain=10)
        assert set(tracker.ids()) == {"111", "222"}
        assert tracker.startup_pin_id() == "999"
