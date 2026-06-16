"""WatchDog gain/milestone alerts must use live Kraken data when LIVE_ENABLED=1."""

from __future__ import annotations

import json
import time
from pathlib import Path

from watchdog.config import WatchdogSettings
from watchdog.engine import WatchdogEngine


def _settings(tmp_path: Path, *, live_enabled: bool = True, quiet_mode: bool = True) -> WatchdogSettings:
    return WatchdogSettings(
        enabled=True,
        poll_seconds=10,
        stale_minutes=5,
        discord_webhook="",
        discord_pin_major=True,
        trade_usd_threshold=25,
        pnl_pct_threshold=0.05,
        drawdown_warn_pct=0.10,
        error_cooldown_minutes=15,
        auto_pause_score=25,
        error_burst_count=5,
        error_burst_minutes=10,
        heartbeat_minutes=0,
        quiet_mode=quiet_mode,
        error_pin_count=3,
        error_pin_window_minutes=30,
        milestone_cooldown_minutes=60,
        live_enabled=live_enabled,
        live_state_file=tmp_path / ".live_state.json",
        live_session_start_file=tmp_path / "live_session_start.json",
        paper_portfolio_file=tmp_path / "paper_portfolio.json",
        bot_root=tmp_path,
        log_dir=tmp_path / "logs",
        receipts_dir=tmp_path / "receipts",
        state_file=tmp_path / ".paper_state.json",
        runtime_log=tmp_path / "logs" / "runtime.log",
        diagnostics_dir=tmp_path / "diagnostics",
        watchdog_state_file=tmp_path / ".watchdog_state.json",
    )


def _write_live_state(tmp_path: Path, *, portfolio_balances: dict, baseline: float) -> None:
    (tmp_path / "live_session_start.json").write_text(
        json.dumps(
            {
                "baseline_portfolio_usd": baseline,
                "peak_portfolio_usd": baseline,
                "usd_prices": {"USD": 1.0, "ETH": 1700.0, "ADA": 0.18},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / ".live_state.json").write_text(
        json.dumps(
            {
                "balances": portfolio_balances,
                "risk": {
                    "baseline_portfolio": baseline,
                    "peak_portfolio": baseline,
                    "live_trades_completed": 1,
                },
            }
        ),
        encoding="utf-8",
    )


def test_live_mode_uses_live_portfolio_for_gain_detection(tmp_path: Path) -> None:
    _write_live_state(
        tmp_path,
        portfolio_balances={"USD": 100.0, "ETH": 0.9, "ADA": 0.0},
        baseline=1630.0,
    )
    engine = WatchdogEngine(_settings(tmp_path, live_enabled=True, quiet_mode=False))
    engine.state.last_milestone_alert_at = 0.0
    engine.state.last_live_pnl_band = 0

    alerts = engine._check_live_portfolio()

    assert alerts == []


def test_live_mode_milestone_alert_uses_live_label(tmp_path: Path) -> None:
    _write_live_state(
        tmp_path,
        portfolio_balances={"USD": 100.0, "ETH": 0.9, "ADA": 0.0},
        baseline=1000.0,
    )
    engine = WatchdogEngine(_settings(tmp_path, live_enabled=True, quiet_mode=False))
    engine.state.last_milestone_alert_at = 0.0
    engine.state.last_live_pnl_band = 0

    alerts = engine._check_live_portfolio()

    assert len(alerts) == 1
    assert "Live Kraken spot" in alerts[0][0]
    assert "[Paper sim]" not in alerts[0][0]


def test_paper_log_line_does_not_trigger_live_gain_alert(tmp_path: Path) -> None:
    _write_live_state(
        tmp_path,
        portfolio_balances={"USD": 266.0, "ETH": 0.79, "ADA": 24.5},
        baseline=1654.0,
    )
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    session_log = log_dir / "2026-06-15_00-00_to_2026-06-15_04-00_PDT.log"
    session_log.write_text(
        "Portfolio:  $5,688.25  (PnL +4034.31 | drawdown 0.00%)\n",
        encoding="utf-8",
    )

    settings = _settings(tmp_path, live_enabled=True)
    engine = WatchdogEngine(settings)
    engine.state.last_milestone_alert_at = 0.0
    engine.state.last_live_pnl_band = 0

    paper_alerts = engine._check_session_logs()
    live_alerts = engine._check_live_portfolio()

    assert paper_alerts == []
    assert live_alerts == []


def test_paper_spike_triggers_paper_alert_only_when_not_live(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    session_log = log_dir / "2026-06-15_00-00_to_2026-06-15_04-00_PDT.log"
    session_log.write_text(
        "Portfolio:  $5,688.25  (PnL +4034.31 | drawdown 0.00%)\n",
        encoding="utf-8",
    )

    engine = WatchdogEngine(_settings(tmp_path, live_enabled=False, quiet_mode=False))
    engine.state.last_milestone_alert_at = 0.0
    engine.state.last_pnl_band = 0

    alerts = engine._check_session_logs()

    assert len(alerts) == 1
    assert "[Paper sim]" in alerts[0][0]
    assert "$5,688.25" in alerts[0][0]


def test_quiet_mode_suppresses_milestone_alerts(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    session_log = log_dir / "2026-06-15_00-00_to_2026-06-15_04-00_PDT.log"
    session_log.write_text(
        "Portfolio:  $5,688.25  (PnL +4034.31 | drawdown 0.00%)\n",
        encoding="utf-8",
    )

    engine = WatchdogEngine(_settings(tmp_path, live_enabled=False, quiet_mode=True))
    engine.state.last_milestone_alert_at = 0.0
    engine.state.last_pnl_band = 0

    assert engine._check_session_logs() == []


def test_milestone_cooldown_blocks_rapid_respan(tmp_path: Path) -> None:
    engine = WatchdogEngine(_settings(tmp_path, live_enabled=False, quiet_mode=False))
    engine.state.last_milestone_alert_at = time.time()
    engine.state.last_pnl_band = 48

    alerts = engine._portfolio_alerts_for(
        portfolio=5793.0,
        pnl=4139.0,
        drawdown_pct=0.0,
        baseline=1654.0,
        source="paper",
    )

    assert alerts == []
