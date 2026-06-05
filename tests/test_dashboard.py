"""Dashboard parser and API smoke tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from dashboard.config import DashboardSettings
from dashboard.parsers.auditor import _list_audit_reports, _parse_report_summary
from dashboard.parsers.series import (
    _parse_confidence,
    _parse_money,
    _parse_receipt_time,
    build_forecasts,
    build_portfolio_history,
    build_trades_series,
    parse_forecast_table,
)
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


# --- series.py: forecast/money parsing edge cases -------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("$1,234.50", pytest.approx(1234.50)),
        ("12.50", pytest.approx(12.50)),
        ("-12.50", pytest.approx(-12.50)),
        ("($5.00)", pytest.approx(-5.00)),
        ("  -$2,000.00 ", pytest.approx(-2000.00)),
        ("+3.21", pytest.approx(3.21)),
    ],
)
def test_parse_money_values(raw, expected):
    assert _parse_money(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "—", "-", "N/A", "abc", "$"])
def test_parse_money_returns_none_for_blank_or_invalid(raw):
    assert _parse_money(raw) is None


def test_parse_money_zero_keeps_sign_neutral():
    assert _parse_money("0") == pytest.approx(0.0)


def test_parse_confidence_valid_and_invalid():
    assert _parse_confidence(" 0.42 ") == pytest.approx(0.42)
    assert _parse_confidence("high") is None
    assert _parse_confidence("") is None


# --- series.py: receipt-time day bucketing --------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2026-06-02 16:26:26 PDT", "2026-06-02"),
        ("2026-06-02 16:26:26", "2026-06-02"),
        ("2026-06-02", "2026-06-02"),
    ],
)
def test_parse_receipt_time_extracts_day(raw, expected):
    assert _parse_receipt_time(raw) == expected


def test_parse_receipt_time_unknown_for_short_garbage():
    assert _parse_receipt_time("xx") == "unknown"


# --- series.py: portfolio history time series -----------------------------

def _market_check_block(time_str: str, portfolio: str, pnl: str, drawdown: str) -> str:
    return (
        "==================================================\n"
        f"MARKET CHECK - {time_str}\n"
        "==================================================\n"
        f"Portfolio:  ${portfolio}  (PnL {pnl} | drawdown {drawdown})\n"
        "\n"
        "Decision: HOLD\n"
    )


def test_build_portfolio_history_parses_drawdown_and_pnl_deltas(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    text = (
        _market_check_block("2026-06-02 20:00:11 PDT", "1,908.73", "-124.83", "7.05%")
        + "\n"
        + _market_check_block("2026-06-02 20:05:11 PDT", "1,925.00", "-108.56", "6.20%")
    )
    (logs / "2026-06-02_PDT.log").write_text(text, encoding="utf-8")

    hist = build_portfolio_history(_settings(tmp_path))
    assert len(hist["points"]) == 2
    first, second = hist["points"]
    assert first["portfolio_usd"] == pytest.approx(1908.73)
    assert first["drawdown_pct"] == pytest.approx(0.0705)
    assert second["drawdown_pct"] == pytest.approx(0.0620)
    # One delta between the two consecutive baseline_pnl readings.
    assert len(hist["pnl_deltas"]) == 1
    assert hist["pnl_deltas"][0]["delta_pnl"] == pytest.approx(16.27)


def test_build_portfolio_history_empty_when_no_logs(tmp_path):
    (tmp_path / "logs").mkdir()
    hist = build_portfolio_history(_settings(tmp_path))
    assert hist["points"] == []
    assert hist["pnl_deltas"] == []


# --- series.py: per-day trade aggregation ---------------------------------

def _write_receipt(path: Path, *, time_str: str, gain_loss: str) -> None:
    path.write_text(
        "==================================================\n"
        "TRADE RECEIPT\n"
        "==================================================\n"
        f"Time:  {time_str}\n"
        "\n"
        "Traded 1.0000 ADA to $1.00 because test\n"
        "\n"
        f"Gain/Loss:  {gain_loss}\n"
        "==================================================\n",
        encoding="utf-8",
    )


def test_build_trades_series_buckets_by_day(tmp_path):
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    _write_receipt(receipts / "r1.txt", time_str="2026-06-01 10:00:00 PDT", gain_loss="+$3.00 (gain)")
    _write_receipt(receipts / "r2.txt", time_str="2026-06-01 11:00:00 PDT", gain_loss="-$1.00 (loss)")
    _write_receipt(receipts / "r3.txt", time_str="2026-06-02 09:00:00 PDT", gain_loss="+$5.50 (gain)")

    series = build_trades_series(_settings(tmp_path))
    buckets = {b["bucket"]: b for b in series["buckets"]}

    assert set(buckets) == {"2026-06-01", "2026-06-02"}
    assert buckets["2026-06-01"]["trade_count"] == 2
    assert buckets["2026-06-01"]["net_pnl"] == pytest.approx(2.00)
    assert buckets["2026-06-02"]["trade_count"] == 1
    assert buckets["2026-06-02"]["net_pnl"] == pytest.approx(5.50)
    # Buckets are sorted ascending by day.
    assert [b["bucket"] for b in series["buckets"]] == ["2026-06-01", "2026-06-02"]
    assert len(series["recent"]) == 3


def test_build_trades_series_empty_dir(tmp_path):
    (tmp_path / "receipts").mkdir()
    series = build_trades_series(_settings(tmp_path))
    assert series["buckets"] == []
    assert series["recent"] == []
