"""Tests for bot.paper_portfolio and related RiskState stale-state pruning."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from bot.paper_broker import RiskState
from bot.paper_portfolio import PaperPortfolioLog


def test_write_and_load_roundtrip(tmp_path: Path):
    path = tmp_path / "paper_portfolio.json"
    log = PaperPortfolioLog(path)
    log.write(
        holdings={"ETH": 0.41, "AAVE": 6.9, "USD": 0.0},
        usd_prices={"ETH": 2091.0, "AAVE": 85.7},
        portfolio_usd=2126.45,
        baseline_pnl=-0.30,
        drawdown_pct=0.0012,
        updated_at="2026-05-25 22:01:22 PDT",
    )
    snap = log.load()
    assert snap is not None
    assert snap.portfolio_usd == 2126.45
    assert snap.baseline_pnl == -0.30
    assert set(snap.balances()) == {"ETH", "AAVE"}
    assert snap.holdings["ETH"]["usd_value"] > 800


def test_format_text_lists_holdings(tmp_path: Path):
    path = tmp_path / "paper_portfolio.json"
    log = PaperPortfolioLog(path)
    log.write(
        holdings={"ADA": 83.0},
        usd_prices={"ADA": 0.24},
        portfolio_usd=19.99,
        baseline_pnl=0.0,
        drawdown_pct=0.0,
    )
    text = log.format_text()
    assert "Paper portfolio" in text
    assert "ADA" in text
    assert "$19.99" in text


def test_clear_removes_file(tmp_path: Path):
    path = tmp_path / "paper_portfolio.json"
    log = PaperPortfolioLog(path)
    log.write(
        holdings={"ETH": 1.0},
        usd_prices={"ETH": 2000.0},
        portfolio_usd=2000.0,
        baseline_pnl=0.0,
        drawdown_pct=0.0,
    )
    assert path.exists()
    log.clear()
    assert not path.exists()
    assert log.load() is None


def test_bootstrap_from_paper_state(tmp_path: Path):
    state = tmp_path / ".paper_state.json"
    state.write_text(
        '{"balances": {"ETH": 0.41, "AAVE": 6.9, "USD": 0}, '
        '"risk": {"baseline_portfolio": 2000, "peak_portfolio": 2100}}',
        encoding="utf-8",
    )
    path = tmp_path / "paper_portfolio.json"
    log = PaperPortfolioLog(path)
    snap = log.bootstrap_from_state(state)
    assert snap is not None
    assert path.exists()
    assert set(snap.balances()) == {"ETH", "AAVE"}
    text = log.format_text()
    assert "AAVE" in text
    assert "$2,126" not in text or "pending" in text.lower() or "0.4100" in text


def test_format_text_falls_back_to_state(tmp_path: Path):
    state = tmp_path / ".paper_state.json"
    state.write_text(
        '{"balances": {"ADA": 83.0}, "risk": {}}',
        encoding="utf-8",
    )
    path = tmp_path / "paper_portfolio.json"
    log = PaperPortfolioLog(path)
    text = log.format_text(state_file=state)
    assert "ADA" in text
    assert "Bootstrapped" in text or "paper state" in text.lower()


# ---------------------------------------------------------------------------
# RiskState stale-state-on-disk regression tests (BACKLOG: stale-state audit)
# ---------------------------------------------------------------------------

class TestRiskStateStaleStatePruning:
    """Loading a .paper_state.json with TTL-based fields past their window
    must not carry stale values into the live bot.

    These tests cover the same class of bug that was fixed for
    .auditor_state.json (proposals with expired expires_at) and
    .watchdog_state.json (old wall-clock timestamps).
    """

    def test_expired_paused_until_is_cleared_on_load(self):
        """paused_until in the past must be reset to None so the bot does not
        wake up in spurious hibernation."""
        past = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        state = RiskState.from_dict({"paused_until": past})
        assert state.paused_until is None

    def test_future_paused_until_is_preserved_on_load(self):
        """paused_until still in the future must survive the round-trip."""
        future = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
        state = RiskState.from_dict({"paused_until": future})
        assert state.paused_until == future

    def test_stale_hour_window_resets_trade_counter(self):
        """hour_window_start older than 1h must reset trades_this_hour to 0
        so the hourly trade limiter starts fresh after a restart."""
        old_window = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        state = RiskState.from_dict({
            "hour_window_start": old_window,
            "trades_this_hour": 7,
        })
        assert state.trades_this_hour == 0
        assert state.hour_window_start is None

    def test_active_hour_window_preserves_trade_counter(self):
        """hour_window_start within the last hour must keep trades_this_hour."""
        recent_window = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        state = RiskState.from_dict({
            "hour_window_start": recent_window,
            "trades_this_hour": 5,
        })
        assert state.trades_this_hour == 5
        assert state.hour_window_start == recent_window

    def test_malformed_paused_until_is_cleared(self):
        """A non-parseable paused_until string should not propagate."""
        state = RiskState.from_dict({"paused_until": "not-a-datetime"})
        assert state.paused_until is None

    def test_malformed_hour_window_resets_counter(self):
        """A non-parseable hour_window_start should zero the trade counter."""
        state = RiskState.from_dict({
            "hour_window_start": "garbage",
            "trades_this_hour": 9,
        })
        assert state.trades_this_hour == 0
        assert state.hour_window_start is None

    def test_none_paused_until_stays_none(self):
        """Explicit None must be preserved (normal no-pause state)."""
        state = RiskState.from_dict({"paused_until": None})
        assert state.paused_until is None

    def test_discord_pins_has_no_ttl_fields(self, tmp_path: Path):
        """.discord_pins.json stores Discord message IDs only — no timestamps.

        Confirms the file has no TTL-based fields requiring pruning on load;
        reconcile() handles ID staleness against the live channel instead."""
        from bot.pin_tracker import PinTracker

        pins_file = tmp_path / ".discord_pins.json"
        tracker = PinTracker(pins_file, channel_id="123", max_retain=10)
        tracker.register("msg-1")
        tracker.register("msg-2")

        # Reload — both IDs should survive (no TTL to prune)
        tracker2 = PinTracker(pins_file, channel_id="123", max_retain=10)
        assert "msg-1" in tracker2.ids()
        assert "msg-2" in tracker2.ids()
