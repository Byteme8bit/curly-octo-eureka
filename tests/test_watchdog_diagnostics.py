"""Circuit breaker diagnostic dedup — regression for inverted alert logic (051)."""
from __future__ import annotations

from pathlib import Path

from watchdog.config import WatchdogSettings
from watchdog.engine import WatchdogEngine
from watchdog.state import WatchdogState


def _settings(root: Path, *, quiet: bool = False) -> WatchdogSettings:
    diag = root / "diagnostics"
    diag.mkdir(exist_ok=True)
    return WatchdogSettings(
        enabled=True,
        poll_seconds=10,
        stale_minutes=5.0,
        discord_webhook="",
        discord_pin_major=True,
        trade_usd_threshold=25.0,
        pnl_pct_threshold=0.05,
        drawdown_warn_pct=0.10,
        error_cooldown_minutes=15.0,
        auto_pause_score=25,
        error_burst_count=5,
        error_burst_minutes=10.0,
        heartbeat_minutes=0.0,
        quiet_mode=quiet,
        error_pin_count=3,
        error_pin_window_minutes=30.0,
        milestone_cooldown_minutes=60.0,
        live_enabled=False,
        live_state_file=root / ".live_state.json",
        live_session_start_file=root / "live_session_start.json",
        paper_portfolio_file=root / "paper_portfolio.json",
        bot_root=root,
        log_dir=root / "logs",
        receipts_dir=root / "receipts",
        state_file=root / ".paper_state.json",
        runtime_log=root / "logs" / "runtime.log",
        diagnostics_dir=diag,
        watchdog_state_file=root / ".watchdog_state.json",
    )


def test_mark_diagnostic_seen_only_first_time():
    state = WatchdogState()
    assert state.mark_diagnostic_seen("circuit_breaker_test.json") is True
    assert state.mark_diagnostic_seen("circuit_breaker_test.json") is False


def test_check_diagnostics_alerts_once_per_file(tmp_path: Path):
    settings = _settings(tmp_path)
    diag_file = settings.diagnostics_dir / "circuit_breaker_20260613-212756 PDT.json"
    diag_file.write_text("{}", encoding="utf-8")

    engine = WatchdogEngine(settings)
    alerts = engine._check_diagnostics()
    assert len(alerts) == 1
    assert "212756" in alerts[0][0]

    repeat = engine._check_diagnostics()
    assert repeat == []


def test_check_diagnostics_suppressed_in_quiet_mode(tmp_path: Path):
    settings = _settings(tmp_path, quiet=True)
    (settings.diagnostics_dir / "circuit_breaker_new.json").write_text("{}", encoding="utf-8")

    engine = WatchdogEngine(settings)
    assert engine._check_diagnostics() == []


def test_prime_marks_existing_diagnostics_seen(tmp_path: Path):
    settings = _settings(tmp_path)
    (settings.diagnostics_dir / "circuit_breaker_old.json").write_text("{}", encoding="utf-8")

    engine = WatchdogEngine(settings)
    engine.prime()
    assert "circuit_breaker_old.json" in engine.state.seen_diagnostics
    assert engine._check_diagnostics() == []
