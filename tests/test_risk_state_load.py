"""Regression tests for RiskState.from_dict() TTL-pruning (feature 029).

These tests verify that stale paused_until and expired hour_window_start values
are stripped on load so a restarted bot does not inherit a phantom hibernate
window or a stale hourly trade counter.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from bot.paper_broker import RiskState


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# paused_until pruning
# ---------------------------------------------------------------------------

def test_from_dict_clears_expired_paused_until():
    """A paused_until in the past must be dropped so the bot is not stuck in hibernate."""
    past = _iso(_now() - timedelta(hours=2))
    state = RiskState.from_dict({"paused_until": past, "hibernate_alert_sent": True})
    assert state.paused_until is None
    assert state.hibernate_alert_sent is False


def test_from_dict_keeps_future_paused_until():
    """A paused_until still in the future must be preserved as-is."""
    future = _iso(_now() + timedelta(hours=3))
    state = RiskState.from_dict({"paused_until": future, "hibernate_alert_sent": True})
    assert state.paused_until == future
    assert state.hibernate_alert_sent is True


def test_from_dict_clears_malformed_paused_until():
    """A corrupt / unparseable paused_until must be cleared gracefully."""
    state = RiskState.from_dict({"paused_until": "not-a-date"})
    assert state.paused_until is None


# ---------------------------------------------------------------------------
# hour_window_start / trades_this_hour pruning
# ---------------------------------------------------------------------------

def test_from_dict_resets_stale_hour_window():
    """If hour_window_start is more than 1 hour old, reset the window + counter."""
    old_window = _iso(_now() - timedelta(hours=2))
    state = RiskState.from_dict({
        "hour_window_start": old_window,
        "trades_this_hour": 5,
    })
    assert state.hour_window_start is None
    assert state.trades_this_hour == 0


def test_from_dict_keeps_recent_hour_window():
    """A window that started less than 1 hour ago must be preserved."""
    recent_window = _iso(_now() - timedelta(minutes=30))
    state = RiskState.from_dict({
        "hour_window_start": recent_window,
        "trades_this_hour": 3,
    })
    assert state.hour_window_start == recent_window
    assert state.trades_this_hour == 3


def test_from_dict_resets_malformed_hour_window():
    """A corrupt hour_window_start is cleared and trades counter is zeroed."""
    state = RiskState.from_dict({
        "hour_window_start": "garbage",
        "trades_this_hour": 7,
    })
    assert state.hour_window_start is None
    assert state.trades_this_hour == 0


def test_from_dict_none_data_returns_defaults():
    """from_dict(None) must return a clean default RiskState."""
    state = RiskState.from_dict(None)
    assert state.paused_until is None
    assert state.hour_window_start is None
    assert state.trades_this_hour == 0
