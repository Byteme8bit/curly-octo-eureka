"""Regression tests for RiskState.from_dict stale-field pruning (feature 029).

These tests load stale JSON fixtures and assert that expired TTL fields are
cleared so the bot never wakes up in an artificially paused or wrong-hour state.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from bot.paper_broker import RiskState


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _past(hours: float) -> str:
    return _iso(datetime.now(timezone.utc) - timedelta(hours=hours))


def _future(hours: float) -> str:
    return _iso(datetime.now(timezone.utc) + timedelta(hours=hours))


# ---------------------------------------------------------------------------
# paused_until pruning
# ---------------------------------------------------------------------------


def test_from_dict_clears_expired_paused_until():
    """Regression: expired paused_until must not survive a load cycle."""
    data = {"paused_until": _past(2)}  # 2 hours in the past
    state = RiskState.from_dict(data)
    assert state.paused_until is None


def test_from_dict_keeps_future_paused_until():
    """A pause that has not yet expired must be preserved."""
    future_str = _future(3)
    data = {"paused_until": future_str}
    state = RiskState.from_dict(data)
    assert state.paused_until == future_str


def test_from_dict_handles_malformed_paused_until():
    """Garbage paused_until must not crash; it should be silently discarded."""
    data = {"paused_until": "not-a-date"}
    state = RiskState.from_dict(data)
    assert state.paused_until is None


# ---------------------------------------------------------------------------
# hour_window_start / trades_this_hour pruning
# ---------------------------------------------------------------------------


def test_from_dict_resets_stale_hour_window():
    """Regression: hour_window_start older than 1h must reset trades_this_hour."""
    data = {
        "hour_window_start": _past(2),   # 2 hours ago
        "trades_this_hour": 7,
    }
    state = RiskState.from_dict(data)
    assert state.hour_window_start is None
    assert state.trades_this_hour == 0


def test_from_dict_keeps_fresh_hour_window():
    """A window started < 1 hour ago must not be touched."""
    recent_str = _past(0.25)  # 15 minutes ago
    data = {
        "hour_window_start": recent_str,
        "trades_this_hour": 3,
    }
    state = RiskState.from_dict(data)
    assert state.hour_window_start == recent_str
    assert state.trades_this_hour == 3


def test_from_dict_handles_malformed_hour_window():
    """Garbage hour_window_start must not crash; trades_this_hour resets."""
    data = {"hour_window_start": "bad-date", "trades_this_hour": 5}
    state = RiskState.from_dict(data)
    assert state.hour_window_start is None
    assert state.trades_this_hour == 0


def test_from_dict_none_data_returns_defaults():
    """from_dict(None) must return a clean RiskState."""
    state = RiskState.from_dict(None)
    assert state.paused_until is None
    assert state.hour_window_start is None
    assert state.trades_this_hour == 0
