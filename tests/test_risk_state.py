"""Regression tests for RiskState.from_dict() stale-TTL pruning.

These verify that loading a persisted RiskState on bot restart does NOT
carry over stale values for paused_until or hour_window_start / trades_this_hour.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from bot.paper_broker import RiskState


def _utc_iso(delta_seconds: float) -> str:
    """Return an ISO timestamp offset from now by delta_seconds."""
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)).isoformat()


class TestRiskStateStalePausedUntil:
    """paused_until that has already elapsed must be cleared on load."""

    def test_expired_paused_until_is_cleared(self):
        data = {"paused_until": _utc_iso(-1)}  # 1 s in the past
        state = RiskState.from_dict(data)
        assert state.paused_until is None

    def test_future_paused_until_is_kept(self):
        ts = _utc_iso(+3600)  # 1 h in the future
        data = {"paused_until": ts}
        state = RiskState.from_dict(data)
        assert state.paused_until == ts

    def test_paused_until_none_is_fine(self):
        state = RiskState.from_dict({"paused_until": None})
        assert state.paused_until is None

    def test_paused_until_unparseable_is_cleared(self):
        data = {"paused_until": "not-a-date"}
        state = RiskState.from_dict(data)
        assert state.paused_until is None


class TestRiskStateStaleHourWindow:
    """hour_window_start older than 1 h must reset trades_this_hour to 0."""

    def test_expired_hour_window_resets_trade_count(self):
        data = {
            "hour_window_start": _utc_iso(-3700),  # > 1 h ago
            "trades_this_hour": 5,
        }
        state = RiskState.from_dict(data)
        assert state.hour_window_start is None
        assert state.trades_this_hour == 0

    def test_fresh_hour_window_keeps_trade_count(self):
        ts = _utc_iso(-1800)  # 30 min ago — within the hour window
        data = {"hour_window_start": ts, "trades_this_hour": 3}
        state = RiskState.from_dict(data)
        assert state.hour_window_start == ts
        assert state.trades_this_hour == 3

    def test_hour_window_start_none_is_fine(self):
        state = RiskState.from_dict({"hour_window_start": None, "trades_this_hour": 0})
        assert state.hour_window_start is None
        assert state.trades_this_hour == 0

    def test_hour_window_unparseable_resets_trade_count(self):
        data = {"hour_window_start": "bad-ts", "trades_this_hour": 7}
        state = RiskState.from_dict(data)
        assert state.hour_window_start is None
        assert state.trades_this_hour == 0

    def test_empty_dict_gives_defaults(self):
        state = RiskState.from_dict({})
        assert state.paused_until is None
        assert state.hour_window_start is None
        assert state.trades_this_hour == 0

    def test_none_dict_gives_defaults(self):
        state = RiskState.from_dict(None)
        assert state.paused_until is None
        assert state.trades_this_hour == 0
