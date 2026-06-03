"""Dashboard parser and API smoke tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from dashboard.config import DashboardSettings
from dashboard.parsers.auditor import _list_audit_reports, _parse_report_summary
from dashboard.parsers.tradebot import _extract_ticks_from_log, _parse_receipt
from dashboard.parsers.watchdog import _filter_watchdog_lines, _health_from_state
from watchdog.state import WatchdogState

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "dashboard"


def test_extract_ticks_from_log():
    text = (FIXTURES / "sample_session_snippet.txt").read_text(encoding="utf-8")
    ticks = _extract_ticks_from_log(text)
    assert len(ticks) == 1
    t = ticks[0]
    assert t["time"] == "2026-06-02 20:00:11 PDT"
    assert t["decision"] == "HOLD"
    assert t["portfolio_usd"] == 1908.73
    assert t["baseline_pnl"] == -124.83
    assert any("fee hurdle" in r for r in t["rotation_blocked"])


def test_parse_receipt():
    row = _parse_receipt(FIXTURES / "sample_receipt.txt")
    assert row is not None
    assert "AVAX" in row["summary"]
    assert row["gain_loss"].startswith("-$")


def test_parse_audit_report():
    row = _parse_report_summary(FIXTURES / "sample_audit.md")
    assert row is not None
    assert row["trigger"] == "scheduled"
    assert row["proposal_count"] == 1
    assert len(row["news_headlines"]) == 1


def test_watchdog_health_and_lines():
    state = WatchdogState(trades_session=3, watchdog_pause_count=1)
    settings = DashboardSettings(
        root=Path("."),
        host="127.0.0.1",
        port=8765,
        refresh_seconds=15,
        paper_portfolio_file=Path("paper_portfolio.json"),
        paper_state_file=Path(".paper_state.json"),
        watchdog_state_file=Path(".watchdog_state.json"),
        auditor_state_file=Path(".auditor_state.json"),
        runtime_overrides_file=Path("runtime_overrides.json"),
        log_dir=Path("logs"),
        runtime_log=Path("logs/runtime.log"),
        discord_chat_log=Path("logs/discord_chat.log"),
        receipts_dir=Path("receipts"),
        reports_dir=Path("reports"),
        backlog_file=Path("BACKLOG.md"),
        error_burst_count=5,
        error_burst_minutes=10.0,
        auto_pause_score=25,
    )
    health = _health_from_state(settings, state, drawdown=0.06)
    assert 0 <= health["score"] <= 100
    lines = _filter_watchdog_lines([
        "[2026-06-02] --> **Watchdog heartbeat**",
        "[2026-06-02] regular tick line",
    ])
    assert len(lines) == 1
    assert "heartbeat" in lines[0]


def test_list_audit_reports_empty(tmp_path):
    assert _list_audit_reports(tmp_path / "missing") == []


def test_fastapi_overview_endpoint():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from dashboard.app import create_app

    client = TestClient(create_app())
    r = client.get("/api/meta")
    assert r.status_code == 200
    assert "refresh_seconds" in r.json()
    r2 = client.get("/")
    assert r2.status_code == 200
