"""Dashboard parser and API smoke tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from dashboard.config import DashboardSettings
from dashboard.parsers.auditor import _list_audit_reports, _parse_report_summary
from dashboard.parsers.series import build_forecasts, parse_forecast_table
from dashboard.parsers.timeline import build_timeline
from dashboard.parsers.tradebot import _extract_ticks_from_log, _parse_receipt, _parse_gain_loss_usd
from dashboard.parsers.watchdog import _filter_watchdog_lines, _health_from_state
from watchdog.state import WatchdogState

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "dashboard"


def _settings(root: Path) -> DashboardSettings:
    return DashboardSettings(
        root=root,
        host="127.0.0.1",
        port=8765,
        refresh_seconds=15,
        paper_portfolio_file=root / "paper_portfolio.json",
        paper_state_file=root / ".paper_state.json",
        watchdog_state_file=root / ".watchdog_state.json",
        auditor_state_file=root / ".auditor_state.json",
        runtime_overrides_file=root / "runtime_overrides.json",
        log_dir=root / "logs",
        runtime_log=root / "logs/runtime.log",
        discord_chat_log=root / "logs/discord_chat.log",
        receipts_dir=root / "receipts",
        reports_dir=root / "reports",
        backlog_file=root / "BACKLOG.md",
        error_burst_count=5,
        error_burst_minutes=10.0,
        auto_pause_score=25,
    )


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
    assert row["gain_loss_usd"] == pytest.approx(-2.58)


def test_parse_gain_loss_usd_positive():
    assert _parse_gain_loss_usd("+$3.21 (gain)") == pytest.approx(3.21)


def test_parse_audit_report():
    row = _parse_report_summary(FIXTURES / "sample_audit.md")
    assert row is not None
    assert row["trigger"] == "scheduled"
    assert row["proposal_count"] == 1
    assert len(row["news_headlines"]) == 1
    assert len(row["forecast_bands"]) == 2
    assert row["forecast_bands"][0]["horizon"] == "24h"
    assert row["forecast_bands"][0]["expected_pnl"] == pytest.approx(-12.50)


def test_parse_forecast_table():
    raw = (FIXTURES / "sample_audit.md").read_text(encoding="utf-8")
    bands = parse_forecast_table(raw)
    assert len(bands) == 2
    assert bands[1]["method"] == "trade_rate_extrapolation"
    assert bands[1]["confidence"] == pytest.approx(0.12)


def test_build_forecasts_from_reports(tmp_path):
    day = tmp_path / "reports" / "2026-06-02"
    day.mkdir(parents=True)
    (day / "audit-test.md").write_text(
        (FIXTURES / "sample_audit.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    fc = build_forecasts(_settings(tmp_path))
    assert fc["source"] is not None
    assert len(fc["bands"]) == 2


def test_watchdog_health_and_lines():
    state = WatchdogState(trades_session=3, watchdog_pause_count=1)
    health = _health_from_state(_settings(Path(".")), state, drawdown=0.06)
    assert 0 <= health["score"] <= 100
    lines = _filter_watchdog_lines([
        "[2026-06-02] --> **Watchdog heartbeat**",
        "[2026-06-02] regular tick line",
    ])
    assert len(lines) == 1
    assert "heartbeat" in lines[0]


def test_list_audit_reports_empty(tmp_path):
    assert _list_audit_reports(tmp_path / "missing") == []


def test_timeline_merges_events(tmp_path):
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    (receipts / "r1.txt").write_text(
        (FIXTURES / "sample_receipt.txt").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    tl = build_timeline(_settings(tmp_path))
    types = {e["type"] for e in tl["events"]}
    assert "trade" in types


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
    assert "Command Center" in r2.text


def test_fastapi_new_endpoints():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from dashboard.app import create_app

    client = TestClient(create_app())
    for path in (
        "/api/overview",
        "/api/portfolio/history",
        "/api/trades/series",
        "/api/forecasts",
        "/api/timeline",
    ):
        resp = client.get(path)
        assert resp.status_code == 200, path
        body = resp.json()
        assert isinstance(body, dict)


def test_overview_includes_summary_and_forecasts():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from dashboard.app import create_app

    client = TestClient(create_app())
    data = client.get("/api/overview").json()
    assert "summary" in data
    assert "forecasts" in data
    assert "timeline" in data
