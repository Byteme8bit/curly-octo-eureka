"""Tests for bot.circuit_breaker — global drawdown safety guard.

The circuit breaker is a capital-protection control: a 15% peak-to-trough
drawdown trips a Global Emergency Pause (re-evaluation mode) that can only be
cleared manually. A regression here means the bot keeps trading through a
portfolio meltdown, so these tests pin down the trigger threshold, the
idempotent latch behaviour, the defensive de-risking intents, and the
diagnostic dump.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from bot.circuit_breaker import CircuitBreaker, CircuitBreakerEvent


def _make_state(**overrides):
    """Duck-typed risk state matching the attributes CircuitBreaker touches."""
    state = SimpleNamespace(
        peak_portfolio=1000.0,
        reevaluation_mode=False,
        circuit_breaker_at=None,
        paused_until="2099-01-01T00:00:00+00:00",
        hibernate_alert_sent=True,
    )
    for key, value in overrides.items():
        setattr(state, key, value)
    return state


def _make_breaker(tmp_path: Path, limit: float = 0.15, **state_overrides):
    state = _make_state(**state_overrides)
    saves = []
    breaker = CircuitBreaker(
        risk_state=state,
        drawdown_limit_pct=limit,
        save_callback=lambda: saves.append(True),
        diagnostic_dir=tmp_path / "diagnostics",
    )
    return breaker, state, saves


# ---------------------------------------------------------------------------
# check() — trigger logic
# ---------------------------------------------------------------------------

def test_check_no_trigger_when_peak_not_set(tmp_path):
    breaker, state, saves = _make_breaker(tmp_path, peak_portfolio=0.0)
    assert breaker.check(10.0) is None
    assert state.reevaluation_mode is False
    assert saves == []


def test_check_no_trigger_below_limit(tmp_path):
    breaker, state, saves = _make_breaker(tmp_path, peak_portfolio=1000.0)
    # 10% drawdown, below the 15% limit.
    assert breaker.check(900.0) is None
    assert state.reevaluation_mode is False
    assert saves == []


def test_check_triggers_at_exact_limit(tmp_path):
    breaker, state, saves = _make_breaker(tmp_path, limit=0.15, peak_portfolio=1000.0)
    # Exactly 15% drawdown must trip (the guard is `drawdown < limit -> skip`).
    event = breaker.check(850.0)
    assert isinstance(event, CircuitBreakerEvent)
    assert state.reevaluation_mode is True
    assert len(saves) == 1


def test_check_triggers_above_limit_and_sets_state(tmp_path):
    breaker, state, saves = _make_breaker(tmp_path, limit=0.15, peak_portfolio=2000.0)
    event = breaker.check(1500.0)  # 25% drawdown

    assert event is not None
    assert event.portfolio_value == 1500.0
    assert event.peak_portfolio == 2000.0
    assert abs(event.drawdown_pct - 0.25) < 1e-9
    assert event.triggered_at.tzinfo is not None

    # State latched for manual review.
    assert state.reevaluation_mode is True
    assert state.circuit_breaker_at is not None
    assert state.paused_until is None
    assert state.hibernate_alert_sent is False
    assert len(saves) == 1


def test_check_is_idempotent_once_in_reevaluation(tmp_path):
    breaker, state, saves = _make_breaker(tmp_path, peak_portfolio=1000.0)
    # First catastrophic drop trips the breaker.
    assert breaker.check(500.0) is not None
    saves.clear()
    # A further drop while already latched must NOT re-fire or re-save.
    assert breaker.check(400.0) is None
    assert saves == []


# ---------------------------------------------------------------------------
# in_reevaluation / clear_reevaluation
# ---------------------------------------------------------------------------

def test_in_reevaluation_reflects_state(tmp_path):
    breaker, state, _ = _make_breaker(tmp_path)
    assert breaker.in_reevaluation() is False
    state.reevaluation_mode = True
    assert breaker.in_reevaluation() is True


def test_clear_reevaluation_resets_and_saves(tmp_path):
    breaker, state, saves = _make_breaker(
        tmp_path,
        reevaluation_mode=True,
        circuit_breaker_at="2026-06-01T00:00:00+00:00",
    )
    breaker.clear_reevaluation()
    assert state.reevaluation_mode is False
    assert state.circuit_breaker_at is None
    assert len(saves) == 1


# ---------------------------------------------------------------------------
# status_message
# ---------------------------------------------------------------------------

def test_status_message_empty_when_not_tripped(tmp_path):
    breaker, _, _ = _make_breaker(tmp_path)
    assert breaker.status_message() == ""


def test_status_message_includes_limit_and_timestamp(tmp_path):
    breaker, _, _ = _make_breaker(
        tmp_path,
        limit=0.15,
        reevaluation_mode=True,
        circuit_breaker_at="2026-06-01T12:00:00+00:00",
    )
    msg = breaker.status_message()
    assert "RE-EVALUATION MODE" in msg
    assert "15%" in msg
    assert "resume-trading" in msg
    assert "unknown" not in msg


def test_status_message_handles_missing_timestamp(tmp_path):
    breaker, _, _ = _make_breaker(
        tmp_path,
        reevaluation_mode=True,
        circuit_breaker_at=None,
    )
    assert "unknown" in breaker.status_message()


# ---------------------------------------------------------------------------
# defensive_intents
# ---------------------------------------------------------------------------

def test_defensive_intents_derisks_volatile_into_usd(tmp_path):
    breaker, _, _ = _make_breaker(tmp_path)
    intents = breaker.defensive_intents(
        holdings={"ETH": 1.0, "ADA": 100.0},
        usd_prices={"ETH": 2000.0, "ADA": 1.0},
        safe_assets=("USD",),
        dust_usd=5.0,
    )
    by_asset = {i.from_asset: i for i in intents}
    assert set(by_asset) == {"ETH", "ADA"}
    for intent in intents:
        assert intent.to_asset == "USD"
        assert intent.is_defensive is True
        assert intent.size_pct == 1.0
        assert intent.strategy_name == "circuit_breaker"


def test_defensive_intents_skips_safe_assets_and_usd(tmp_path):
    breaker, _, _ = _make_breaker(tmp_path)
    intents = breaker.defensive_intents(
        holdings={"USD": 500.0, "USDC": 100.0, "ETH": 1.0},
        usd_prices={"USDC": 1.0, "ETH": 2000.0},
        safe_assets=("USDC",),  # USD always implicitly safe
        dust_usd=5.0,
    )
    assert [i.from_asset for i in intents] == ["ETH"]


def test_defensive_intents_skips_dust_and_nonpositive_qty(tmp_path):
    breaker, _, _ = _make_breaker(tmp_path)
    intents = breaker.defensive_intents(
        holdings={"ADA": 3.0, "DOT": 0.0, "SOL": -1.0, "ETH": 1.0},
        usd_prices={"ADA": 1.0, "DOT": 5.0, "SOL": 100.0, "ETH": 2000.0},
        dust_usd=5.0,  # ADA is worth $3 < $5 dust floor
        safe_assets=("USD",),
    )
    # Only ETH survives: ADA is dust, DOT is zero qty, SOL is negative.
    assert [i.from_asset for i in intents] == ["ETH"]


def test_defensive_intents_targets_first_safe_asset_when_no_usd(tmp_path):
    breaker, _, _ = _make_breaker(tmp_path)
    intents = breaker.defensive_intents(
        holdings={"ETH": 1.0},
        usd_prices={"ETH": 2000.0},
        safe_assets=("DAI", "USDC"),  # no plain "USD"
        dust_usd=5.0,
    )
    assert len(intents) == 1
    # "USD" is implicitly added to the safe set, so it remains the target.
    assert intents[0].to_asset == "USD"


def test_defensive_intents_missing_price_treated_as_dust(tmp_path):
    breaker, _, _ = _make_breaker(tmp_path)
    intents = breaker.defensive_intents(
        holdings={"XRP": 100.0},
        usd_prices={},  # unknown price -> value 0 -> below any dust floor
        safe_assets=("USD",),
        dust_usd=1.0,
    )
    assert intents == []


# ---------------------------------------------------------------------------
# dump_diagnostics
# ---------------------------------------------------------------------------

def test_dump_diagnostics_writes_payload(tmp_path):
    breaker, _, _ = _make_breaker(tmp_path)
    event = CircuitBreakerEvent(
        portfolio_value=1500.0,
        peak_portfolio=2000.0,
        drawdown_pct=0.25,
        triggered_at=datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
    )
    holdings = {"ETH": 1.0}
    prices = {"ETH": 2000.0}
    path = breaker.dump_diagnostics(event, holdings, prices, extra={"note": "test"})

    assert path.exists()
    assert path.parent == tmp_path / "diagnostics"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["portfolio_value"] == 1500.0
    assert payload["peak_portfolio"] == 2000.0
    assert payload["drawdown_pct"] == 0.25
    assert payload["holdings"] == holdings
    assert payload["usd_prices"] == prices
    assert payload["extra"] == {"note": "test"}
    assert payload["triggered_at"] == event.triggered_at.isoformat()


def test_dump_diagnostics_creates_missing_directory(tmp_path):
    breaker, _, _ = _make_breaker(tmp_path)
    assert not (tmp_path / "diagnostics").exists()
    event = CircuitBreakerEvent(
        portfolio_value=10.0,
        peak_portfolio=20.0,
        drawdown_pct=0.5,
        triggered_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    path = breaker.dump_diagnostics(event, {}, {})
    assert path.exists()
    # Default extra is an empty dict, not None.
    assert json.loads(path.read_text(encoding="utf-8"))["extra"] == {}
