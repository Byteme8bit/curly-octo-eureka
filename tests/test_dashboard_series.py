"""Tests for dashboard time-series, forecast, and timeline parsers.

Covers the new dashboard-v2 (#28) parsing/aggregation logic that ships chart
and feed data: financial-string parsing, day-bucketing of receipts, portfolio
history deltas/drawdown parsing, and timeline severity + ordering. These are
pure, deterministic functions with large blast radius (every chart/feed reads
them), so each case asserts exact values rather than smoke-checking shapes.
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
from dashboard.parsers.timeline import _parse_sort_key, build_timeline


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
    receipts_dir: Path,
    name: str,
    *,
    time_str: str,
    summary: str,
    gain_loss: str,
    fee: str | None = None,
) -> None:
    receipts_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "==================================================",
        "TRADE RECEIPT",
        "==================================================",
        f"Time:  {time_str}",
        "",
        f"Traded {summary}",
        "",
        f"Gain/Loss:  {gain_loss}",
    ]
    if fee is not None:
        lines.append(f"Fee:  {fee}")
    lines.append("==================================================")
    (receipts_dir / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# _parse_money — financial string parsing (forecast bands, PnL columns)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("$12.50", 12.50),
        ("12.50", 12.50),
        ("$1,234.56", 1234.56),
        ("$-12.50", -12.50),       # explicit minus
        ("-$12.50", -12.50),       # minus before currency
        ("($25.00)", -25.00),      # accounting-style negative
        ("$0.00", 0.00),
        ("  $7.25  ", 7.25),       # surrounding whitespace
    ],
)
def test_parse_money_numeric(raw, expected):
    assert _parse_money(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", ["", "   ", "—", "-", "N/A", "abc", "$"])
def test_parse_money_non_numeric_returns_none(raw):
    assert _parse_money(raw) is None


def test_parse_confidence():
    assert _parse_confidence("0.45") == pytest.approx(0.45)
    assert _parse_confidence("—") is None
    assert _parse_confidence("") is None


# --------------------------------------------------------------------------- #
# _parse_receipt_time — day bucket key extraction
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "time_str,expected",
    [
        ("2026-06-02 16:26:26 PDT", "2026-06-02"),
        ("2026-06-02 16:26:26", "2026-06-02"),
        ("2026-06-02", "2026-06-02"),
        ("", "unknown"),
        ("garbage", "unknown"),
    ],
)
def test_parse_receipt_time(time_str, expected):
    assert _parse_receipt_time(time_str) == expected


# --------------------------------------------------------------------------- #
# build_trades_series — per-day aggregation of count / net PnL / fees
# --------------------------------------------------------------------------- #


def test_build_trades_series_buckets_and_aggregates(tmp_path):
    receipts = tmp_path / "receipts"
    _write_receipt(
        receipts,
        "r1.txt",
        time_str="2026-06-01 09:00:00 PDT",
        summary="0.5 ETH to $1000.00 because rotation",
        gain_loss="+$10.00 (gain)",
        fee="$1.00",
    )
    _write_receipt(
        receipts,
        "r2.txt",
        time_str="2026-06-01 15:00:00 PDT",
        summary="2.0 ADA to $4.00 because mitigating losses",
        gain_loss="-$4.00 (loss)",
        fee="$0.50",
    )
    _write_receipt(
        receipts,
        "r3.txt",
        time_str="2026-06-02 11:00:00 PDT",
        summary="1.0 SOL to $2.50 because momentum",
        gain_loss="+$2.50 (gain)",  # no Fee line -> fee defaults to 0
    )

    series = build_trades_series(_settings(tmp_path))
    buckets = {b["bucket"]: b for b in series["buckets"]}

    # Two days, sorted ascending by day key.
    assert [b["bucket"] for b in series["buckets"]] == ["2026-06-01", "2026-06-02"]

    day1 = buckets["2026-06-01"]
    assert day1["trade_count"] == 2
    assert day1["net_pnl"] == pytest.approx(6.00)   # +10 - 4
    assert day1["fees"] == pytest.approx(1.50)      # 1.00 + 0.50

    day2 = buckets["2026-06-02"]
    assert day2["trade_count"] == 1
    assert day2["net_pnl"] == pytest.approx(2.50)
    assert day2["fees"] == pytest.approx(0.0)       # missing Fee line -> 0

    assert len(series["recent"]) == 3
    assert all("summary" in t for t in series["recent"])


def test_build_trades_series_empty_dir_is_safe(tmp_path):
    series = build_trades_series(_settings(tmp_path))
    assert series["buckets"] == []
    assert series["recent"] == []


# --------------------------------------------------------------------------- #
# build_portfolio_history — points, drawdown parsing, baseline PnL deltas
# --------------------------------------------------------------------------- #


def _write_window_log(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    content = (
        "==================================================\n"
        "MARKET CHECK - 2026-06-02 20:00:11 PDT\n"
        "==================================================\n"
        "Portfolio:  $1,000.00  (PnL -50.00 | drawdown 5.00%)\n"
        "\n"
        "Decision: HOLD\n"
        "\n"
        "==================================================\n"
        "MARKET CHECK - 2026-06-02 20:05:11 PDT\n"
        "==================================================\n"
        "Portfolio:  $1,010.00  (PnL -40.00 | drawdown 3.00%)\n"
        "\n"
        "Decision: BUY\n"
    )
    (log_dir / "2026-06-02_20-00_PDT.log").write_text(content, encoding="utf-8")


def test_build_portfolio_history_points_and_deltas(tmp_path):
    _write_window_log(tmp_path / "logs")
    hist = build_portfolio_history(_settings(tmp_path))

    points = hist["points"]
    assert len(points) == 2
    assert points[0]["portfolio_usd"] == pytest.approx(1000.00)
    assert points[1]["portfolio_usd"] == pytest.approx(1010.00)

    # drawdown "%" strings are normalized to fractions.
    assert points[0]["drawdown_pct"] == pytest.approx(0.05)
    assert points[1]["drawdown_pct"] == pytest.approx(0.03)

    # baseline PnL deltas computed between consecutive ticks.
    assert len(hist["pnl_deltas"]) == 1
    assert hist["pnl_deltas"][0]["delta_pnl"] == pytest.approx(10.00)  # -40 - (-50)


def test_build_portfolio_history_no_logs_is_safe(tmp_path):
    hist = build_portfolio_history(_settings(tmp_path))
    assert hist["points"] == []
    assert hist["pnl_deltas"] == []


# --------------------------------------------------------------------------- #
# timeline — sort-key parsing, severity classification, ordering
# --------------------------------------------------------------------------- #


def test_parse_sort_key_orders_chronologically():
    # The comparator must order the bot's real timestamp format (with a tz
    # suffix) chronologically, both within a day and across days. NOTE: for
    # tz-suffixed strings the epoch component currently stays 0.0 and the raw
    # string tail drives ordering; that is correct for this fixed-width format
    # but is a latent parsing weakness flagged in the PR.
    assert _parse_sort_key("2026-06-02 12:00:00 PDT") > _parse_sort_key("2026-06-02 10:00:00 PDT")
    assert _parse_sort_key("2026-06-03 01:00:00 PDT") > _parse_sort_key("2026-06-02 23:00:00 PDT")
    # A naive (no-tz) timestamp parses to a real epoch.
    assert _parse_sort_key("2026-06-02 12:00:00")[0] > 0.0
    # Unparseable times fall back to epoch-zero so they sort last (oldest).
    assert _parse_sort_key("")[0] == 0.0
    assert _parse_sort_key("garbage")[0] == 0.0


def test_build_timeline_severity_and_ordering(tmp_path):
    tradebot = {
        "recent_trades": [
            {
                "time": "2026-06-02 10:00:00 PDT",
                "summary": "won trade",
                "gain_loss": "+$5.00",
                "gain_loss_usd": 5.0,
            },
            {
                "time": "2026-06-02 12:00:00 PDT",
                "summary": "lost trade",
                "gain_loss": "-$3.00",
                "gain_loss_usd": -3.0,
            },
        ],
        "portfolio": {"drawdown_pct": 0.0},
    }
    watchdog = {"recent_errors": [], "session": {}, "alert_lines": []}
    auditor = {
        "recent_reports": [],
        "pending_proposals": [
            {
                "created_at": "2026-06-02 11:00:00 PDT",
                "knob": "TRADE_SIZE_PCT",
                "current_value": "0.1",
                "proposed_value": "0.2",
                "severity": "high",
            }
        ],
        "run_markers": {},
    }

    tl = build_timeline(
        _settings(tmp_path),
        tradebot=tradebot,
        watchdog=watchdog,
        auditor=auditor,
    )
    events = tl["events"]
    assert tl["total"] == 3

    # Newest-first ordering: 12:00 trade, 11:00 proposal, 10:00 trade.
    assert [e["time"] for e in events] == [
        "2026-06-02 12:00:00 PDT",
        "2026-06-02 11:00:00 PDT",
        "2026-06-02 10:00:00 PDT",
    ]

    by_title = {e["title"]: e for e in events}
    assert by_title["won trade"]["severity"] == "good"
    assert by_title["lost trade"]["severity"] == "bad"
    assert by_title["Proposal: TRADE_SIZE_PCT"]["severity"] == "bad"  # high -> bad


def test_build_timeline_trade_with_unknown_pnl_is_info(tmp_path):
    tradebot = {
        "recent_trades": [
            {"time": "2026-06-02 10:00:00 PDT", "summary": "unknown pnl", "gain_loss_usd": None}
        ]
    }
    tl = build_timeline(
        _settings(tmp_path),
        tradebot=tradebot,
        watchdog={"recent_errors": [], "session": {}, "alert_lines": []},
        auditor={"recent_reports": [], "pending_proposals": [], "run_markers": {}},
    )
    assert tl["events"][0]["severity"] == "info"
