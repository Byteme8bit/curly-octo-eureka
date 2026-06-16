"""Tests for Discord ``TradeBot -force`` command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bot.discord_bot import parse_command
from bot.engine import TradingEngine
from bot.preflight import PreFlightResult
from bot.strategies.base import StrategyResult, TradeIntent


def test_force_command_parses() -> None:
    result = parse_command("TradeBot -force")
    assert result is not None
    assert result.action == "force"
    assert result.deprecated is False


def test_force_trade_alias_parses() -> None:
    result = parse_command("TB -force-trade")
    assert result is not None
    assert result.action == "force"


def _minimal_engine(tmp_path: Path) -> TradingEngine:
    engine = TradingEngine.__new__(TradingEngine)
    engine.settings = MagicMock(
        dca_enabled=False,
        profit_only_mode=True,
        force_trade_log_file=tmp_path / "force_trade.log",
    )
    engine._mirror_mode = False
    engine._live_mode = False
    engine._crash_status = None
    engine.broker = MagicMock(halted=False)
    engine.circuit_breaker = MagicMock(in_reevaluation=lambda: False)
    engine.live_circuit_breaker = None
    engine.live_broker = None
    engine.data = MagicMock()
    engine.data.fetch_all_candles.return_value = {}
    engine.trade_context = MagicMock()
    engine.markets = MagicMock()
    engine.constraints = MagicMock()
    engine.governor = MagicMock()
    engine.governor.apply.side_effect = lambda intents, adaptive: (intents, "", [])
    engine.risk = MagicMock()
    engine.risk.adaptive_status.return_value = MagicMock(active=False)
    engine.risk.pnl_from_baseline.return_value = 1.0
    engine.risk.drawdown_pct.return_value = 0.0
    engine.risk.record_trade = MagicMock()
    engine.auditor = MagicMock()
    engine.receipts = MagicMock()
    engine.receipts.save.return_value = tmp_path / "receipt.txt"
    engine.governor.record_trade = MagicMock()
    engine._build_context = MagicMock(return_value=None)
    engine._holdings = MagicMock(return_value={"USD": 1000.0, "ETH": 1.0})
    engine._usd_prices = MagicMock(return_value={"ETH": 3000.0, "USD": 1.0})
    engine._write_portfolio_file = MagicMock()
    engine._record_strategy_fill = MagicMock()
    engine._is_accumulation_intent = TradingEngine._is_accumulation_intent.__get__(
        engine, TradingEngine
    )
    engine._trade_context_block = MagicMock(return_value=None)
    engine._intent_trade_usd = MagicMock(return_value=50.0)
    return engine


def test_force_trade_blocked_in_reevaluation(tmp_path: Path) -> None:
    engine = _minimal_engine(tmp_path)
    engine.circuit_breaker.in_reevaluation = MagicMock(return_value=True)

    reply = TradingEngine._handle_force_trade(engine)

    assert "Re-evaluation mode" in reply
    log = (tmp_path / "force_trade.log").read_text(encoding="utf-8")
    assert "HALTED" in log


def test_force_trade_executes_best_offensive(tmp_path: Path) -> None:
    engine = _minimal_engine(tmp_path)
    good = TradeIntent(
        from_asset="USD",
        to_asset="ETH",
        reason="test edge",
        size_pct=0.1,
        edge=0.01,
        strategy_name="momentum",
    )
    weak = TradeIntent(
        from_asset="ETH",
        to_asset="USD",
        reason="weaker",
        size_pct=0.1,
        edge=0.001,
        strategy_name="momentum",
    )
    engine.strategy = MagicMock()
    engine.strategy.evaluate.return_value = StrategyResult(
        signals={},
        scores={},
        reasons={},
        sizes={},
        intents=[weak, good],
    )
    engine.constraints.trim_overweight_intents.return_value = []

    route = MagicMock(hops=1, symbols=("ETH/USD",))

    def eval_side_effect(intent, **kwargs):
        if intent is good:
            return (0.012, True, "", 1)
        return (0.001, True, "", 1)

    engine._evaluate_force_intent = MagicMock(side_effect=eval_side_effect)
    trade = {
        "from_asset": "USD",
        "to_asset": "ETH",
        "symbol": "ETH/USD",
        "gain_loss": 0.5,
        "fee_usd": 0.1,
        "size_pct": 0.1,
    }
    engine._try_execute_intent = MagicMock(return_value=(trade, ""))
    engine.broker.portfolio_value.return_value = 2000.0

    reply = TradingEngine._handle_force_trade(engine)

    assert "Force trade executed" in reply
    engine._try_execute_intent.assert_called_once()
    assert engine._try_execute_intent.call_args.args[0] is good
    log = (tmp_path / "force_trade.log").read_text(encoding="utf-8")
    assert "EXECUTED" in log
    assert "USD->ETH" in log


def test_force_trade_reports_best_blocked_edge(tmp_path: Path) -> None:
    engine = _minimal_engine(tmp_path)
    intent = TradeIntent(
        from_asset="ETH",
        to_asset="SOL",
        reason="near miss",
        size_pct=0.05,
        edge=0.0003,
        strategy_name="stat_arb",
    )
    engine.strategy = MagicMock()
    engine.strategy.evaluate.return_value = StrategyResult(
        signals={},
        scores={},
        reasons={},
        sizes={},
        intents=[intent],
    )
    engine.constraints.trim_overweight_intents.return_value = []
    engine._evaluate_force_intent = MagicMock(
        return_value=(
            0.0003,
            False,
            "Profit-only mode: expected net +0.0003 <= 0 after fees",
            1,
        )
    )

    reply = TradingEngine._handle_force_trade(engine)

    assert "no profitable route" in reply.lower()
    assert "ETH → SOL" in reply
    assert "Profit-only mode" in reply
    log = (tmp_path / "force_trade.log").read_text(encoding="utf-8")
    assert "BLOCKED" in log


def test_force_trade_dca_fallback_when_no_offensive(tmp_path: Path) -> None:
    engine = _minimal_engine(tmp_path)
    engine.settings.dca_enabled = True
    dca = TradeIntent(
        from_asset="USD",
        to_asset="AAPLx",
        reason="scheduled DCA",
        size_pct=0.02,
        edge=0.0,
        is_accumulation=True,
        strategy_name="equity_dca",
    )
    blocked_offensive = TradeIntent(
        from_asset="ETH",
        to_asset="ADA",
        reason="blocked",
        size_pct=0.05,
        edge=0.0,
        strategy_name="momentum",
    )
    engine.strategy = MagicMock()
    engine.strategy.evaluate.return_value = StrategyResult(
        signals={},
        scores={},
        reasons={},
        sizes={},
        intents=[blocked_offensive, dca],
    )
    engine.constraints.trim_overweight_intents.return_value = []

    def eval_side_effect(intent, **kwargs):
        if intent is dca:
            return (0.0, True, "", 1)
        return (0.0001, False, "below min net", 1)

    engine._evaluate_force_intent = MagicMock(side_effect=eval_side_effect)
    trade = {
        "from_asset": "USD",
        "to_asset": "AAPLx",
        "symbol": "AAPLx/USD",
        "gain_loss": -0.05,
        "fee_usd": 0.05,
        "size_pct": 0.02,
    }
    engine._try_execute_intent = MagicMock(return_value=(trade, ""))
    engine.broker.portfolio_value.return_value = 2000.0

    reply = TradingEngine._handle_force_trade(engine)

    assert "DCA fallback" in reply
    assert engine._try_execute_intent.call_args.args[0] is dca
