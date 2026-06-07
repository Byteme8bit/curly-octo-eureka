"""Tests for bot.structured_log — JSONL event sink (feature 041)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot.structured_log import StructuredLogger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_events(log_dir: Path) -> list[dict]:
    path = log_dir / "events.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


# ---------------------------------------------------------------------------
# Trade events
# ---------------------------------------------------------------------------

class TestLogTrade:
    def test_creates_events_jsonl(self, tmp_path: Path):
        sl = StructuredLogger(tmp_path)
        sl.log_trade({"from_asset": "USD", "to_asset": "ETH", "gain_loss": 0.0})
        assert (tmp_path / "events.jsonl").exists()

    def test_trade_record_fields(self, tmp_path: Path):
        sl = StructuredLogger(tmp_path)
        trade = {
            "strategy_name": "momentum_rotation",
            "from_asset": "USD",
            "to_asset": "ETH",
            "from_qty": 500.0,
            "to_qty": 0.25,
            "fee_usd": 2.0,
            "gain_loss": 5.50,
            "type": "usd",
            "hops": 1,
            "reason": "ETH leads",
        }
        sl.log_trade(trade)
        events = _read_events(tmp_path)
        assert len(events) == 1
        ev = events[0]
        assert ev["event"] == "trade"
        assert ev["strategy"] == "momentum_rotation"
        assert ev["from_asset"] == "USD"
        assert ev["to_asset"] == "ETH"
        assert ev["from_qty"] == pytest.approx(500.0)
        assert ev["to_qty"] == pytest.approx(0.25)
        assert ev["fee_usd"] == pytest.approx(2.0)
        assert ev["gain_loss"] == pytest.approx(5.50)
        assert ev["hops"] == 1
        assert ev["reason"] == "ETH leads"
        assert "ts" in ev

    def test_multiple_trades_appended(self, tmp_path: Path):
        sl = StructuredLogger(tmp_path)
        sl.log_trade({"from_asset": "USD", "to_asset": "ETH"})
        sl.log_trade({"from_asset": "ETH", "to_asset": "AAVE"})
        events = _read_events(tmp_path)
        assert len(events) == 2
        assert events[0]["to_asset"] == "ETH"
        assert events[1]["to_asset"] == "AAVE"

    def test_minimal_trade_dict_no_crash(self, tmp_path: Path):
        sl = StructuredLogger(tmp_path)
        sl.log_trade({})
        events = _read_events(tmp_path)
        assert events[0]["event"] == "trade"
        assert events[0]["strategy"] == "unknown"

    def test_reason_truncated_at_500_chars(self, tmp_path: Path):
        sl = StructuredLogger(tmp_path)
        sl.log_trade({"reason": "x" * 600})
        ev = _read_events(tmp_path)[0]
        assert len(ev["reason"]) == 500


# ---------------------------------------------------------------------------
# Pre-flight reject events
# ---------------------------------------------------------------------------

class TestLogPreflightReject:
    def test_preflight_record_fields(self, tmp_path: Path):
        sl = StructuredLogger(tmp_path)
        sl.log_preflight_reject(
            strategy="triangular_arbitrage",
            from_asset="ETH",
            to_asset="ETH",
            gross_pct=0.0012,
            fee_pct=0.0040,
            slippage_pct=0.0005,
            net_pct=-0.0033,
            threshold=0.001,
            reason="Pre-flight reject: net -0.0033 <= min 0.001",
        )
        events = _read_events(tmp_path)
        assert len(events) == 1
        ev = events[0]
        assert ev["event"] == "preflight_reject"
        assert ev["strategy"] == "triangular_arbitrage"
        assert ev["from_asset"] == "ETH"
        assert ev["to_asset"] == "ETH"
        assert ev["gross_pct"] == pytest.approx(0.0012, abs=1e-9)
        assert ev["fee_pct"] == pytest.approx(0.004, abs=1e-9)
        assert ev["net_pct"] == pytest.approx(-0.0033, abs=1e-9)
        assert ev["threshold"] == pytest.approx(0.001, abs=1e-9)
        assert "ts" in ev

    def test_preflight_and_trade_in_same_file(self, tmp_path: Path):
        sl = StructuredLogger(tmp_path)
        sl.log_preflight_reject(
            strategy="stat_arb",
            from_asset="ETH",
            to_asset="BTC",
            gross_pct=0.001,
            fee_pct=0.004,
            slippage_pct=0.0005,
            net_pct=-0.0035,
            threshold=0.001,
            reason="rejected",
        )
        sl.log_trade({"from_asset": "ETH", "to_asset": "AAVE"})
        events = _read_events(tmp_path)
        assert len(events) == 2
        assert events[0]["event"] == "preflight_reject"
        assert events[1]["event"] == "trade"


# ---------------------------------------------------------------------------
# BotFileLogger integration: trades are forwarded to events.jsonl
# ---------------------------------------------------------------------------

class TestBotFileLoggerIntegration:
    def test_log_tick_with_trade_writes_jsonl(self, tmp_path: Path):
        from bot.trade_log import BotFileLogger
        from bot.status import StatusSnapshot

        bl = BotFileLogger(tmp_path, rotate_hours=4)

        dummy_result = type("R", (), {
            "scores": {},
            "idle_reason": "test",
            "opportunities": [],
            "blocked": [],
            "intents": [],
        })()
        dummy_status = StatusSnapshot(
            mode="active",
            summary_key="k",
            considering=[],
            idle_reason="",
        )

        trade = {
            "strategy_name": "momentum_rotation",
            "from_asset": "USD",
            "to_asset": "ETH",
            "from_qty": 500.0,
            "to_qty": 0.25,
            "fee_usd": 2.0,
            "gain_loss": 0.0,
            "type": "usd",
            "symbol": "ETH/USD",
            "side": "buy",
            "hops": 1,
            "reason": "test trade",
        }

        bl.log_tick(
            portfolio=1000.0,
            baseline_pnl=0.0,
            drawdown=0.0,
            result=dummy_result,
            holdings={"USD": 500.0, "ETH": 0.25},
            usd_prices={"ETH": 2000.0},
            blocked=[],
            trades=[trade],
            status=dummy_status,
            status_changed=False,
            status_since=None,
        )

        events = _read_events(tmp_path)
        assert any(e["event"] == "trade" and e["to_asset"] == "ETH" for e in events), (
            "log_tick must forward filled trades to events.jsonl"
        )
