"""Regression tests for stale-state-on-disk patterns in persistent state files.

Covers the three files audited in BACKLOG item #041:
  - .paper_state.json  (PaperState / RiskState)
  - .watchdog_state.json  (covered by tests/test_watchdog_state.py)
  - .discord_pins.json  (PinTracker)
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bot.paper_broker import PaperState, RiskState
from bot.pin_tracker import PinTracker


# ---------------------------------------------------------------------------
# .paper_state.json  —  RiskState.from_dict() pruning
# ---------------------------------------------------------------------------


def _past_iso(hours: int = 2) -> str:
    """Return an ISO datetime string `hours` hours in the past."""
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _future_iso(hours: int = 2) -> str:
    """Return an ISO datetime string `hours` hours in the future."""
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def test_risk_state_clears_expired_paused_until():
    """paused_until in the past must be dropped on load — regression for #041.

    Without this fix, reloading a state file written after a drawdown-hibernate
    could cause the bot to start in a paused state even though the pause window
    has long passed.
    """
    risk = RiskState.from_dict({"paused_until": _past_iso(hours=3)})
    assert risk.paused_until is None


def test_risk_state_keeps_future_paused_until():
    """paused_until in the future must be preserved (bot is still in a valid
    hibernate window)."""
    future = _future_iso(hours=2)
    risk = RiskState.from_dict({"paused_until": future})
    assert risk.paused_until == future


def test_risk_state_handles_missing_paused_until():
    """No paused_until key → None, no crash."""
    risk = RiskState.from_dict({})
    assert risk.paused_until is None


def test_paper_state_stale_fixture(tmp_path):
    """Loading a .paper_state.json with an expired paused_until must clear it."""
    fixture: dict = {
        "balances": {"USD": 1000.0, "ETH": 0.5},
        "cost_basis": {"ETH": 900.0},
        "trades": [],
        "risk": {
            "peak_portfolio": 1200.0,
            "baseline_portfolio": 1000.0,
            "paused_until": _past_iso(hours=48),  # 2 days in the past
            "trades_this_hour": 3,
            "hour_window_start": _past_iso(hours=3),  # stale hour window
        },
    }
    state_file = tmp_path / ".paper_state.json"
    state_file.write_text(json.dumps(fixture), encoding="utf-8")

    data = json.loads(state_file.read_text(encoding="utf-8"))
    loaded = PaperState.from_dict(data)

    # Expired pause must be cleared
    assert loaded.risk.paused_until is None
    # Non-TTL fields preserved
    assert loaded.risk.peak_portfolio == 1200.0
    assert loaded.balances["ETH"] == 0.5


# ---------------------------------------------------------------------------
# .discord_pins.json  —  PinTracker (no TTL fields, just sanity checks)
# ---------------------------------------------------------------------------


def test_pin_tracker_loads_clean(tmp_path):
    """.discord_pins.json has no TTL-based fields — all IDs are preserved
    on load (no stale-state-on-disk issue).  This test documents that the
    audit found no pruning needed here."""
    channel = "123456789"
    ids = ["111", "222", "333"]
    state_file = tmp_path / ".discord_pins.json"
    state_file.write_text(
        json.dumps({
            "channel_id": channel,
            "pinned_message_ids": ids,
            "startup_pin_message_id": None,
        }),
        encoding="utf-8",
    )
    tracker = PinTracker(state_file, channel_id=channel, max_retain=10)
    assert tracker.ids() == ids


def test_pin_tracker_ignores_wrong_channel(tmp_path):
    """IDs for a different channel are silently discarded on load."""
    state_file = tmp_path / ".discord_pins.json"
    state_file.write_text(
        json.dumps({
            "channel_id": "old-channel",
            "pinned_message_ids": ["111", "222"],
        }),
        encoding="utf-8",
    )
    tracker = PinTracker(state_file, channel_id="new-channel", max_retain=10)
    assert tracker.ids() == []
