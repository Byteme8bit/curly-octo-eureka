"""Regression tests: stale TTL fields are pruned when loading .paper_state.json.

Feature 038 — RiskState.from_dict() must clear an already-expired paused_until
so a bot that crashed mid-hibernate does not wake up still paused.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bot.paper_broker import PaperBroker, PaperState, RiskState, _prune_paused_until


# ---------------------------------------------------------------------------
# Unit tests for the helper
# ---------------------------------------------------------------------------

def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _future(hours: float = 4.0) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def _past(hours: float = 4.0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours)


class TestPrunePausedUntil:
    def test_none_input_is_noop(self):
        value, cleared = _prune_paused_until(None)
        assert value is None
        assert cleared is False

    def test_future_timestamp_is_preserved(self):
        ts = _iso(_future(4))
        value, cleared = _prune_paused_until(ts)
        assert value == ts
        assert cleared is False

    def test_past_timestamp_is_cleared(self):
        ts = _iso(_past(4))
        value, cleared = _prune_paused_until(ts)
        assert value is None
        assert cleared is True

    def test_unparseable_string_treated_as_expired(self):
        value, cleared = _prune_paused_until("not-a-date")
        assert value is None
        assert cleared is True

    def test_exactly_now_is_cleared(self):
        # A timestamp exactly equal to now should be treated as expired.
        ts = _iso(datetime.now(timezone.utc) - timedelta(seconds=1))
        value, cleared = _prune_paused_until(ts)
        assert value is None
        assert cleared is True


# ---------------------------------------------------------------------------
# RiskState.from_dict() integration
# ---------------------------------------------------------------------------

class TestRiskStateFromDict:
    def test_expired_paused_until_cleared_on_load(self):
        data = {
            "paused_until": _iso(_past(24)),
            "hibernate_alert_sent": True,
        }
        state = RiskState.from_dict(data)
        assert state.paused_until is None, "expired pause must be cleared on load"
        assert state.hibernate_alert_sent is False, "alert flag must reset with cleared pause"

    def test_future_paused_until_preserved(self):
        ts = _iso(_future(4))
        data = {
            "paused_until": ts,
            "hibernate_alert_sent": True,
        }
        state = RiskState.from_dict(data)
        assert state.paused_until == ts
        assert state.hibernate_alert_sent is True

    def test_null_paused_until_unchanged(self):
        state = RiskState.from_dict({"paused_until": None, "hibernate_alert_sent": False})
        assert state.paused_until is None
        assert state.hibernate_alert_sent is False

    def test_missing_paused_until_unchanged(self):
        state = RiskState.from_dict({})
        assert state.paused_until is None

    def test_empty_dict_returns_defaults(self):
        state = RiskState.from_dict({})
        assert state.peak_portfolio == 0.0
        assert state.paused_until is None


# ---------------------------------------------------------------------------
# PaperBroker round-trip via disk: expired pause is gone after reload
# ---------------------------------------------------------------------------

class TestPaperBrokerStaleState:
    def test_reload_clears_expired_paused_until(self, tmp_path: Path):
        """Simulate a crash during hibernate: on next start paused_until is gone."""
        state_file = tmp_path / ".paper_state.json"
        # Write a state file that contains an expired pause timestamp.
        raw = {
            "balances": {"USD": 1000.0, "ETH": 0.0},
            "cost_basis": {},
            "trades": [],
            "risk": {
                "paused_until": _iso(_past(25)),
                "hibernate_alert_sent": True,
                "peak_portfolio": 1100.0,
                "baseline_portfolio": 1000.0,
            },
        }
        state_file.write_text(json.dumps(raw), encoding="utf-8")

        broker = PaperBroker(
            initial_balances={"USD": 1000.0, "ETH": 0.0},
            fee_rate=0.004,
            state_file=state_file,
            reset=False,
        )
        assert broker.state.risk.paused_until is None
        assert broker.state.risk.hibernate_alert_sent is False

    def test_reload_keeps_valid_future_pause(self, tmp_path: Path):
        state_file = tmp_path / ".paper_state.json"
        future_ts = _iso(_future(3))
        raw = {
            "balances": {"USD": 1000.0},
            "cost_basis": {},
            "trades": [],
            "risk": {
                "paused_until": future_ts,
                "hibernate_alert_sent": True,
                "peak_portfolio": 1100.0,
            },
        }
        state_file.write_text(json.dumps(raw), encoding="utf-8")

        broker = PaperBroker(
            initial_balances={"USD": 1000.0},
            fee_rate=0.004,
            state_file=state_file,
            reset=False,
        )
        assert broker.state.risk.paused_until == future_ts
        assert broker.state.risk.hibernate_alert_sent is True
