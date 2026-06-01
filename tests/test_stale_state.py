"""Regression tests: stale TTL fields are pruned when state files are loaded.

Covers the BACKLOG item "Detect other stale-state-on-disk patterns":
  .paper_state.json  — risk.paused_until and risk.hour_window_start
  .watchdog_state.json — seen_diagnostics size cap
  .discord_pins.json  — channel_id mismatch drops all IDs
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bot.paper_broker import PaperBroker, _prune_stale_risk_fields
from bot.paper_broker import RiskState
from bot.pin_tracker import PinTracker
from watchdog.state import WatchdogState


# ---------------------------------------------------------------------------
# .paper_state.json — RiskState TTL fields
# ---------------------------------------------------------------------------


def _make_paper_state(tmp_path: Path, **risk_overrides) -> Path:
    """Write a minimal .paper_state.json fixture to tmp_path."""
    risk = {
        "peak_portfolio": 1000.0,
        "baseline_portfolio": 1000.0,
        "paused_until": None,
        "hibernate_alert_sent": False,
        "trades_this_hour": 0,
        "hour_window_start": None,
    }
    risk.update(risk_overrides)
    path = tmp_path / ".paper_state.json"
    path.write_text(
        json.dumps({"balances": {"USD": 1000.0}, "cost_basis": {}, "trades": [], "risk": risk}),
        encoding="utf-8",
    )
    return path


def test_paper_broker_clears_expired_paused_until(tmp_path: Path):
    """paused_until that is already past must be cleared on load."""
    expired = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    state_file = _make_paper_state(
        tmp_path, paused_until=expired, hibernate_alert_sent=True
    )
    broker = PaperBroker({"USD": 1000.0}, 0.0026, state_file)
    assert broker.state.risk.paused_until is None
    assert broker.state.risk.hibernate_alert_sent is False


def test_paper_broker_keeps_future_paused_until(tmp_path: Path):
    """paused_until that is still in the future must be preserved."""
    future = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
    state_file = _make_paper_state(tmp_path, paused_until=future)
    broker = PaperBroker({"USD": 1000.0}, 0.0026, state_file)
    assert broker.state.risk.paused_until == future


def test_paper_broker_resets_stale_hour_window(tmp_path: Path):
    """hour_window_start older than 1 hour must reset trades_this_hour to 0."""
    stale_window = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    state_file = _make_paper_state(
        tmp_path, hour_window_start=stale_window, trades_this_hour=7
    )
    broker = PaperBroker({"USD": 1000.0}, 0.0026, state_file)
    assert broker.state.risk.hour_window_start is None
    assert broker.state.risk.trades_this_hour == 0


def test_paper_broker_keeps_fresh_hour_window(tmp_path: Path):
    """hour_window_start less than 1 hour ago must be kept intact."""
    fresh_window = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    state_file = _make_paper_state(
        tmp_path, hour_window_start=fresh_window, trades_this_hour=3
    )
    broker = PaperBroker({"USD": 1000.0}, 0.0026, state_file)
    assert broker.state.risk.hour_window_start == fresh_window
    assert broker.state.risk.trades_this_hour == 3


def test_paper_broker_persists_pruned_state_to_disk(tmp_path: Path):
    """After pruning, the on-disk file is rewritten; a second load sees clean state."""
    expired = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    state_file = _make_paper_state(
        tmp_path, paused_until=expired, hibernate_alert_sent=True
    )
    # First load — prunes and persists
    PaperBroker({"USD": 1000.0}, 0.0026, state_file)
    # Second load — file must already be clean
    broker2 = PaperBroker({"USD": 1000.0}, 0.0026, state_file)
    assert broker2.state.risk.paused_until is None


def test_prune_stale_risk_fields_bad_timestamp():
    """Malformed timestamp strings are treated as stale and cleared."""
    risk = RiskState(
        paused_until="not-a-timestamp",
        hibernate_alert_sent=True,
        hour_window_start="also-bad",
        trades_this_hour=4,
    )
    pruned = _prune_stale_risk_fields(risk)
    assert pruned == 2
    assert risk.paused_until is None
    assert risk.hour_window_start is None
    assert risk.trades_this_hour == 0


# ---------------------------------------------------------------------------
# .watchdog_state.json — seen_diagnostics size cap
# ---------------------------------------------------------------------------


def test_watchdog_state_caps_seen_diagnostics_on_load(tmp_path: Path):
    """seen_diagnostics is capped at 500 on load; most-recent entries are kept."""
    path = tmp_path / ".watchdog_state.json"
    diagnostics = [f"diag_{i}" for i in range(600)]
    path.write_text(json.dumps({"seen_diagnostics": diagnostics}), encoding="utf-8")

    state = WatchdogState.load(path)
    assert len(state.seen_diagnostics) == 500
    # Most-recent 500 items retained
    assert state.seen_diagnostics[0] == "diag_100"
    assert state.seen_diagnostics[-1] == "diag_599"


def test_watchdog_state_keeps_small_seen_diagnostics(tmp_path: Path):
    """When fewer than 500 entries, none are dropped."""
    path = tmp_path / ".watchdog_state.json"
    diagnostics = [f"diag_{i}" for i in range(10)]
    path.write_text(json.dumps({"seen_diagnostics": diagnostics}), encoding="utf-8")

    state = WatchdogState.load(path)
    assert len(state.seen_diagnostics) == 10


def test_watchdog_mark_diagnostic_seen_caps_list():
    """mark_diagnostic_seen enforces a 500-item cap at runtime."""
    state = WatchdogState()
    for i in range(600):
        state.mark_diagnostic_seen(f"diag_{i}")
    assert len(state.seen_diagnostics) <= 500
    # Latest items are retained
    assert "diag_599" in state.seen_diagnostics
    assert "diag_0" not in state.seen_diagnostics


# ---------------------------------------------------------------------------
# .discord_pins.json — channel_id mismatch drops all IDs
# ---------------------------------------------------------------------------


def _write_pins(path: Path, *, channel_id: str, ids: list[str], startup: str | None = None) -> None:
    path.write_text(
        json.dumps({
            "channel_id": channel_id,
            "pinned_message_ids": ids,
            "startup_pin_message_id": startup,
        }),
        encoding="utf-8",
    )


def test_pin_tracker_drops_ids_on_channel_mismatch(tmp_path: Path):
    """On load: channel_id mismatch discards all stored pin IDs."""
    path = tmp_path / ".discord_pins.json"
    _write_pins(path, channel_id="old_channel", ids=["111", "222"], startup="333")

    tracker = PinTracker(path, channel_id="new_channel", max_retain=10)
    assert tracker.ids() == []
    assert tracker.startup_pin_id() is None


def test_pin_tracker_loads_matching_channel(tmp_path: Path):
    """On load: matching channel_id correctly restores pin IDs and startup pin."""
    path = tmp_path / ".discord_pins.json"
    _write_pins(path, channel_id="my_channel", ids=["111", "222"], startup="333")

    tracker = PinTracker(path, channel_id="my_channel", max_retain=10)
    assert set(tracker.ids()) == {"111", "222"}
    assert tracker.startup_pin_id() == "333"
    # startup pin must NOT appear in regular ids()
    assert "333" not in tracker.ids()


def test_pin_tracker_startup_pin_excluded_from_ids(tmp_path: Path):
    """startup_pin_message_id stored inside pinned_message_ids is de-duped on load."""
    path = tmp_path / ".discord_pins.json"
    # Deliberately include startup ID in the main list (corrupt/legacy state)
    _write_pins(path, channel_id="ch", ids=["aaa", "bbb", "ccc"], startup="bbb")

    tracker = PinTracker(path, channel_id="ch", max_retain=10)
    assert tracker.startup_pin_id() == "bbb"
    assert "bbb" not in tracker.ids()
    assert set(tracker.ids()) == {"aaa", "ccc"}
