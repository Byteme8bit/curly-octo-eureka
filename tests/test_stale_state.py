"""Regression tests: stale TTL-based fields are pruned when state files are loaded.

Covers three persistent state files:
  - .paper_state.json  (PaperBroker / RiskState)
  - .watchdog_state.json  (WatchdogState)
  - .discord_pins.json  (PinTracker — bounded by max_retain; no TTL fields to prune)
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bot.paper_broker import PaperBroker, RiskState
from watchdog.state import WatchdogState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso_future(hours: float = 2) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _iso_past(hours: float = 2) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _make_broker(tmp_path: Path, state_dict: dict) -> PaperBroker:
    state_file = tmp_path / ".paper_state.json"
    state_file.write_text(json.dumps(state_dict), encoding="utf-8")
    return PaperBroker(
        initial_balances={"USD": 1000.0, "ETH": 0.5},
        fee_rate=0.004,
        state_file=state_file,
    )


# ---------------------------------------------------------------------------
# PaperBroker / RiskState — paused_until
# ---------------------------------------------------------------------------

def test_paper_state_expired_paused_until_is_cleared(tmp_path):
    """paused_until in the past → cleared on load; hibernate_alert_sent reset."""
    broker = _make_broker(tmp_path, {
        "balances": {"USD": 500.0},
        "cost_basis": {},
        "trades": [],
        "risk": {
            "paused_until": _iso_past(hours=3),
            "hibernate_alert_sent": True,
        },
    })
    assert broker.risk.paused_until is None
    assert broker.risk.hibernate_alert_sent is False


def test_paper_state_future_paused_until_is_kept(tmp_path):
    """paused_until in the future → not cleared."""
    future = _iso_future(hours=2)
    broker = _make_broker(tmp_path, {
        "balances": {"USD": 500.0},
        "cost_basis": {},
        "trades": [],
        "risk": {"paused_until": future},
    })
    assert broker.risk.paused_until == future


def test_paper_state_invalid_paused_until_is_cleared(tmp_path):
    """Unparseable paused_until → treated as expired and cleared."""
    broker = _make_broker(tmp_path, {
        "balances": {"USD": 500.0},
        "cost_basis": {},
        "trades": [],
        "risk": {"paused_until": "not-a-date"},
    })
    assert broker.risk.paused_until is None


# ---------------------------------------------------------------------------
# PaperBroker / RiskState — hour_window_start / trades_this_hour
# ---------------------------------------------------------------------------

def test_paper_state_expired_hour_window_resets_trade_counter(tmp_path):
    """hour_window_start > 1 h ago → reset to None; trades_this_hour reset to 0."""
    broker = _make_broker(tmp_path, {
        "balances": {"USD": 500.0},
        "cost_basis": {},
        "trades": [],
        "risk": {
            "hour_window_start": _iso_past(hours=2),
            "trades_this_hour": 7,
        },
    })
    assert broker.risk.hour_window_start is None
    assert broker.risk.trades_this_hour == 0


def test_paper_state_recent_hour_window_is_kept(tmp_path):
    """hour_window_start < 1 h ago → not reset."""
    recent = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    broker = _make_broker(tmp_path, {
        "balances": {"USD": 500.0},
        "cost_basis": {},
        "trades": [],
        "risk": {
            "hour_window_start": recent,
            "trades_this_hour": 3,
        },
    })
    assert broker.risk.hour_window_start == recent
    assert broker.risk.trades_this_hour == 3


def test_paper_state_both_stale_fields_cleared_together(tmp_path):
    """Both paused_until and hour_window_start expired → both cleared."""
    broker = _make_broker(tmp_path, {
        "balances": {"USD": 500.0},
        "cost_basis": {},
        "trades": [],
        "risk": {
            "paused_until": _iso_past(hours=1),
            "hour_window_start": _iso_past(hours=2),
            "trades_this_hour": 5,
            "hibernate_alert_sent": True,
        },
    })
    assert broker.risk.paused_until is None
    assert broker.risk.hour_window_start is None
    assert broker.risk.trades_this_hour == 0
    assert broker.risk.hibernate_alert_sent is False


# ---------------------------------------------------------------------------
# PaperBroker._prune_stale_risk_fields — unit tests
# ---------------------------------------------------------------------------

def test_prune_stale_risk_fields_returns_false_when_nothing_to_do():
    risk = RiskState()
    assert PaperBroker._prune_stale_risk_fields(risk) is False


def test_prune_stale_risk_fields_returns_true_on_any_change():
    risk = RiskState(paused_until=_iso_past(hours=1))
    assert PaperBroker._prune_stale_risk_fields(risk) is True


# ---------------------------------------------------------------------------
# WatchdogState — seen_diagnostics cap
# ---------------------------------------------------------------------------

def test_watchdog_seen_diagnostics_capped_at_500_on_load(tmp_path):
    """A state file with 600+ seen_diagnostics is capped to 500 on load."""
    path = tmp_path / ".watchdog_state.json"
    big_list = [f"diag-{i}" for i in range(600)]
    path.write_text(json.dumps({"seen_diagnostics": big_list}), encoding="utf-8")

    state = WatchdogState.load(path)
    assert len(state.seen_diagnostics) == 500
    # Tail is preserved (most-recent diagnostics kept)
    assert state.seen_diagnostics[-1] == "diag-599"


def test_watchdog_seen_diagnostics_under_500_unchanged_on_load(tmp_path):
    """A state file with fewer than 500 diagnostics is loaded without truncation."""
    path = tmp_path / ".watchdog_state.json"
    short_list = [f"diag-{i}" for i in range(10)]
    path.write_text(json.dumps({"seen_diagnostics": short_list}), encoding="utf-8")

    state = WatchdogState.load(path)
    assert len(state.seen_diagnostics) == 10


def test_watchdog_mark_diagnostic_seen_caps_at_runtime():
    """mark_diagnostic_seen enforces max_retain cap at runtime too."""
    state = WatchdogState()
    state.seen_diagnostics = [f"old-{i}" for i in range(500)]

    result = state.mark_diagnostic_seen("new-diag")

    assert result is True
    assert len(state.seen_diagnostics) == 500
    assert state.seen_diagnostics[-1] == "new-diag"
    assert "old-0" not in state.seen_diagnostics


def test_watchdog_mark_diagnostic_seen_dedup():
    """Duplicate diagnostics return False and do not grow the list."""
    state = WatchdogState()
    state.mark_diagnostic_seen("x")
    result = state.mark_diagnostic_seen("x")
    assert result is False
    assert state.seen_diagnostics.count("x") == 1
