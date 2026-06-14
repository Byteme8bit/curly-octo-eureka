"""Targeted tests for dashboard time-series and financial-aggregation parsing.

Covers the edge-case money/confidence/date parsing helpers in
``dashboard.parsers.series`` plus the two aggregation builders
(``build_portfolio_history`` and ``build_trades_series``) that feed the
dashboard charts. These paths were merged in the "Trader dashboard v2"
change without dedicated coverage; a regression here would silently corrupt
PnL/fee totals and drawdown lines shown to the operator.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dashboard.config import DashboardSettings
from dashboard.parsers.series import (
    _parse_confidence,
    _parse_money,
    _parse_receipt_time,
    build_portfolio_history,
    build_trades_series,
)


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


def _write_receipt(
    path: Path, *, time_str: str, traded: str, gain_loss: str, fee: str | None
) -> None:
    lines = [
        "==================================================",
        "TRADE RECEIPT",
        "==================================================",
        f"Time:  {time_str}",
        "",
        f"Traded {traded}",
        "",
        f"Gain/Loss:  {gain_loss}",
    ]
    if fee is not None:
        lines.append(f"Fee:  {fee}")
    lines.append("==================================================")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# _parse_money — currency/sign/sentinel edge cases
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("$1,234.50", 1234.50),
        ("1234.5", 1234.5),
        ("-$12.50", -12.50),
        ("($12.50)", -12.50),  # accounting-style negative
        ("+$3.21", 3.21),
        ("  $0.00  ", 0.0),
    ],
)
def test_parse_money_values(raw, expected):
    assert _parse_money(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", ["", "—", "-", "N/A", "abc", "$"])
def test_parse_money_sentinels_and_garbage_return_none(raw):
    assert _parse_money(raw) is None


def test_parse_money_negative_zero_is_zero_not_negative():
    # neg flag set but value is 0 -> must not flip to -0.0 confusion
    assert _parse_money("-$0.00") == pytest.approx(0.0)


# --------------------------------------------------------------------------
# _parse_confidence
# --------------------------------------------------------------------------


def test_parse_confidence_valid():
    assert _parse_confidence(" 0.12 ") == pytest.approx(0.12)


@pytest.mark.parametrize("raw", ["high", "", "n/a"])
def test_parse_confidence_invalid_returns_none(raw):
    assert _parse_confidence(raw) is None


# --------------------------------------------------------------------------
# _parse_receipt_time — day bucket key extraction
# --------------------------------------------------------------------------


def test_parse_receipt_time_iso_fast_path():
    assert _parse_receipt_time("2026-06-02 16:26:26 PDT") == "2026-06-02"


def test_parse_receipt_time_short_garbage_is_unknown():
    assert _parse_receipt_time("nope") == "unknown"


def test_parse_receipt_time_non_date_long_string_truncates():
    # Does not match ISO fast-path or strptime; falls back to first 10 chars.
    assert _parse_receipt_time("not a real date here") == "not a real"


# --------------------------------------------------------------------------
# build_portfolio_history — tick -> point projection + pnl deltas
# --------------------------------------------------------------------------


def _session_log_two_ticks() -> str:
    return (
        "==================================================\n"
        "MARKET CHECK - 2026-06-02 20:00:11 PDT\n"
        "==================================================\n"
        "Portfolio:  $1,900.00  (PnL -100.00 | drawdown 5.00%)\n"
        "\n"
        "Decision: HOLD\n"
        "\n"
        "==================================================\n"
        "MARKET CHECK - 2026-06-02 21:00:11 PDT\n"
        "==================================================\n"
        "Portfolio:  $1,950.00  (PnL -50.00 | drawdown 4.00%)\n"
        "\n"
        "Decision: BUY\n"
    )


def test_build_portfolio_history_points_and_deltas(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "session_PDT.log").write_text(_session_log_two_ticks(), encoding="utf-8")

    hist = build_portfolio_history(_settings(tmp_path))
    points = hist["points"]
    assert len(points) == 2

    first, second = points
    assert first["portfolio_usd"] == pytest.approx(1900.00)
    assert first["baseline_pnl"] == pytest.approx(-100.00)
    # "5.00%" string is normalised to a fraction.
    assert first["drawdown_pct"] == pytest.approx(0.05)
    assert second["drawdown_pct"] == pytest.approx(0.04)

    # Exactly one consecutive delta, computed from baseline_pnl.
    assert len(hist["pnl_deltas"]) == 1
    assert hist["pnl_deltas"][0]["delta_pnl"] == pytest.approx(50.0)
    assert hist["pnl_deltas"][0]["time"] == "2026-06-02 21:00:11 PDT"


def test_build_portfolio_history_empty_when_no_logs(tmp_path):
    (tmp_path / "logs").mkdir()
    hist = build_portfolio_history(_settings(tmp_path))
    assert hist["points"] == []
    assert hist["pnl_deltas"] == []


# --------------------------------------------------------------------------
# build_trades_series — per-day count / net PnL / fee aggregation
# --------------------------------------------------------------------------


def test_build_trades_series_buckets_aggregate_pnl_and_fees(tmp_path):
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    _write_receipt(
        receipts / "r1.txt",
        time_str="2026-06-02 16:26:26 PDT",
        traded="3.1 AVAX to $24.93 because mitigating losses",
        gain_loss="-$2.58 (loss)",
        fee="$0.50",
    )
    _write_receipt(
        receipts / "r2.txt",
        time_str="2026-06-02 18:00:00 PDT",
        traded="1.0 ETH to $30.00",
        gain_loss="+$5.00 (gain)",
        fee="$0.25",
    )
    _write_receipt(
        receipts / "r3.txt",
        time_str="2026-06-03 09:00:00 PDT",
        traded="2.0 OP to $10.00",
        gain_loss="+$1.00 (gain)",
        fee="$0.10",
    )

    series = build_trades_series(_settings(tmp_path))
    buckets = {b["bucket"]: b for b in series["buckets"]}

    assert set(buckets) == {"2026-06-02", "2026-06-03"}
    # Buckets are emitted in sorted day order.
    assert [b["bucket"] for b in series["buckets"]] == ["2026-06-02", "2026-06-03"]

    day1 = buckets["2026-06-02"]
    assert day1["trade_count"] == 2
    assert day1["net_pnl"] == pytest.approx(2.42)  # -2.58 + 5.00
    assert day1["fees"] == pytest.approx(0.75)  # 0.50 + 0.25

    day2 = buckets["2026-06-03"]
    assert day2["trade_count"] == 1
    assert day2["net_pnl"] == pytest.approx(1.00)
    assert day2["fees"] == pytest.approx(0.10)

    assert len(series["recent"]) == 3


def test_build_trades_series_missing_fee_counts_as_zero(tmp_path):
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    _write_receipt(
        receipts / "r1.txt",
        time_str="2026-06-04 12:00:00 PDT",
        traded="1.0 BTC to $100.00",
        gain_loss="+$10.00 (gain)",
        fee=None,
    )

    series = build_trades_series(_settings(tmp_path))
    assert len(series["buckets"]) == 1
    bucket = series["buckets"][0]
    assert bucket["fees"] == pytest.approx(0.0)
    assert bucket["net_pnl"] == pytest.approx(10.00)


def test_build_trades_series_empty_dir_is_safe(tmp_path):
    series = build_trades_series(_settings(tmp_path))
    assert series["buckets"] == []
    assert series["recent"] == []
