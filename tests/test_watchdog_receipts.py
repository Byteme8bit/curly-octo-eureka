"""Tests for watchdog receipt handling — no duplicate trade Discord alerts."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from watchdog.config import WatchdogSettings
from watchdog.engine import WatchdogEngine
from watchdog.parsers import TradeEvent


@pytest.fixture
def engine(tmp_path: Path) -> WatchdogEngine:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    settings = WatchdogSettings(
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
        heartbeat_minutes=15.0,
        error_pin_count=3,
        error_pin_window_minutes=30.0,
        bot_root=tmp_path,
        log_dir=log_dir,
        receipts_dir=tmp_path / "receipts",
        state_file=tmp_path / ".paper_state.json",
        runtime_log=log_dir / "runtime.log",
        diagnostics_dir=tmp_path / "diagnostics",
        watchdog_state_file=tmp_path / ".watchdog_state.json",
    )
    eng = WatchdogEngine(settings, post_alert=lambda msg, pin=False: None)
    eng.state.trades_session = 0
    return eng


def test_check_receipts_records_trade_without_discord_alert(engine: WatchdogEngine, tmp_path: Path):
    receipts = tmp_path / "receipts"
    receipts.mkdir(parents=True)
    receipt = receipts / "20260525-213857-ATOM-to-ETH.txt"
    receipt.write_text(
        "Traded 33.9274 ATOM to 0.035294 ETH because triangular arb leg 1/3\n"
        "Fee: $0.19\n"
        "Gain/Loss: +$1.58 (profit)\n",
        encoding="utf-8",
    )

    trade = TradeEvent(
        narrative="Traded 33.9274 ATOM to 0.035294 ETH",
        reason="triangular arb leg 1/3",
        fee_usd=0.19,
        gain_loss_label="+$1.58 (profit)",
        source="receipt",
        source_ref=receipt.name,
    )

    with patch("watchdog.engine.parse_receipt", return_value=trade):
        alerts = engine._check_receipts()

    assert alerts == []
    assert engine.state.trades_session == 1


def test_record_trade_from_receipt_does_not_return_alert(engine: WatchdogEngine):
    trade = TradeEvent(
        narrative="Traded 1 ETH to 100 USDC",
        reason="test",
        fee_usd=0.5,
        gain_loss_label="+$2.00 (profit)",
        source="receipt",
        source_ref="test.txt",
    )
    engine._record_trade_from_receipt(trade)
    assert engine.state.trades_session == 1
