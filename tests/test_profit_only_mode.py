"""Tests for PROFIT_ONLY_MODE — block trades with expected net <= 0."""

from __future__ import annotations

from unittest.mock import MagicMock

from bot.preflight import PreFlightResult, PreFlightValidator
from bot.risk import RiskManager
from bot.strategies.base import TradeIntent


def _risk(*, profit_only: bool, min_net: float = -0.004, adaptive: bool = False) -> RiskManager:
    state = MagicMock()
    state.adaptive_relax_factor = 1.0
    state.session_started_at = "2026-06-15T00:00:00+00:00"
    state.last_trade_at = "2026-06-15T00:00:00+00:00"
    state.adaptive_suspended_at = None
    return RiskManager(
        risk_state=state,
        fee_rate=0.002,
        drawdown_hibernate_pct=0.15,
        hibernate_hours=12,
        trade_cooldown_seconds=45,
        max_trades_per_hour=25,
        min_trade_edge=0.002,
        leader_stable_seconds=180,
        fee_safety_multiplier=1.0,
        idle_reeval_hours=2,
        idle_reeval_max_attempts=3,
        min_net_profit_pct=min_net,
        stat_arb_zscore_threshold=1.8,
        save_callback=lambda: None,
        adaptive_enabled=adaptive,
        profit_only_mode=profit_only,
    )


def test_effective_min_net_profit_never_negative_in_profit_only_mode() -> None:
    risk = _risk(profit_only=True, min_net=-0.004)
    assert risk.effective_min_net_profit() >= 0.0


def test_effective_min_net_profit_allows_negative_floor_when_disabled() -> None:
    risk = _risk(profit_only=False, min_net=-0.004)
    assert risk.effective_min_net_profit() < 0.0


def test_try_execute_intent_blocks_non_positive_net_when_profit_only() -> None:
    from bot.engine import TradingEngine

    engine = MagicMock(spec=TradingEngine)
    engine.settings = MagicMock(profit_only_mode=True)
    engine._mirror_mode = False
    engine._live_mode = False
    engine._crash_status = None
    engine.broker = MagicMock(halted=False)
    engine.markets = MagicMock()
    engine.markets.find_path.return_value = MagicMock(hops=1, symbols=("ETH/USD",))
    engine._intent_trade_usd = MagicMock(return_value=50.0)
    engine.risk = MagicMock()
    engine.risk.path_edge.return_value = 0.0
    engine.risk.effective_min_net_profit.return_value = 0.0005
    engine.risk.approve_action.return_value = MagicMock(allowed=True)
    engine.constraints = MagicMock()
    engine.constraints.validate_intent.return_value = MagicMock(allowed=True, size_pct=0.1)
    engine.preflight = MagicMock()
    engine.preflight.validate.return_value = PreFlightResult(
        allowed=True,
        gross_return_pct=0.001,
        fee_pct=0.002,
        slippage_pct=0.0005,
        net_return_pct=0.0,
        reason="edge case net exactly zero",
    )
    engine._execute_intent = MagicMock()
    engine._trade_context_block = MagicMock(return_value=None)
    engine._is_accumulation_intent = MagicMock(return_value=False)

    intent = TradeIntent(
        from_asset="ETH",
        to_asset="SOL",
        reason="test",
        size_pct=0.1,
        edge=0.001,
        gross_return_pct=0.001,
        is_defensive=False,
    )
    trade, reason = TradingEngine._try_execute_intent(
        engine,
        intent,
        holdings={"ETH": 1.0},
        usd_prices={"ETH": 2000.0, "SOL": 100.0},
        portfolio=2000.0,
    )
    assert trade is None
    assert "Profit-only mode" in reason
    engine._execute_intent.assert_not_called()


def test_try_execute_intent_allows_defensive_when_profit_only() -> None:
    from bot.engine import TradingEngine

    engine = MagicMock(spec=TradingEngine)
    engine.settings = MagicMock(profit_only_mode=True)
    engine._mirror_mode = False
    engine._live_mode = False
    engine._crash_status = None
    engine.broker = MagicMock(halted=False)
    engine.markets = MagicMock()
    engine.markets.find_path.return_value = MagicMock(hops=1, symbols=("ETH/USD",))
    engine._intent_trade_usd = MagicMock(return_value=50.0)
    engine.risk = MagicMock()
    engine.risk.path_edge.return_value = 0.0
    engine.risk.effective_min_net_profit.return_value = 0.0005
    engine.risk.approve_action.return_value = MagicMock(allowed=True)
    engine.risk.record_trade = MagicMock()
    engine.constraints = MagicMock()
    engine.constraints.validate_intent.return_value = MagicMock(allowed=True, size_pct=0.1)
    engine.preflight = MagicMock()
    engine.preflight.validate.return_value = PreFlightResult(
        allowed=True,
        gross_return_pct=0.0,
        fee_pct=0.002,
        slippage_pct=0.0005,
        net_return_pct=-0.0025,
        reason="Defensive exit — pre-flight bypass",
    )
    engine._execute_intent = MagicMock(return_value={"gain_loss": -1.0})
    engine.receipts = MagicMock()
    engine.receipts.save.return_value = "receipt.json"
    engine.governor = MagicMock()
    engine.auditor = MagicMock()
    engine._trade_context_block = MagicMock(return_value=None)
    engine._is_accumulation_intent = MagicMock(return_value=False)

    intent = TradeIntent(
        from_asset="ETH",
        to_asset="USD",
        reason="defensive trim",
        size_pct=0.1,
        edge=0.0,
        gross_return_pct=0.0,
        is_defensive=True,
    )
    trade, reason = TradingEngine._try_execute_intent(
        engine,
        intent,
        holdings={"ETH": 1.0},
        usd_prices={"ETH": 2000.0},
        portfolio=2000.0,
    )
    assert trade is not None
    assert reason == ""


def test_mirror_blocks_non_positive_net_when_profit_only() -> None:
    from bot.engine import TradingEngine
    from bot.markets import PairInfo, RouteLeg, TradeRoute
    from bot.strategies.base import Signal, TradeIntent

    engine = TradingEngine.__new__(TradingEngine)
    engine.settings = MagicMock(
        profit_only_mode=True,
        live_strict_profit=True,
        slippage_buffer_pct=0.0005,
    )
    engine._is_accumulation_intent = MagicMock(return_value=False)
    engine.risk = MagicMock()
    engine.risk.effective_min_net_profit.return_value = 0.0005

    intent = TradeIntent(
        from_asset="ETH",
        to_asset="ETH",
        reason="triangular loop",
        size_pct=0.05,
        edge=0.01,
        gross_return_pct=0.01,
        strategy_name="triangular_arbitrage",
    )
    route = TradeRoute(
        legs=(
            RouteLeg(
                pair=PairInfo(symbol="ETH/USD", base="ETH", quote="USD"),
                side=Signal.SELL,
                from_asset="ETH",
                to_asset="USD",
            ),
        )
    )
    reason = TradingEngine._live_mirror_offensive_block(engine, intent, route, 0.0)
    assert "Profit-only mode" in reason


def test_mirror_blocks_four_leg_offensive_under_live_strict() -> None:
    from bot.engine import TradingEngine
    from bot.markets import PairInfo, RouteLeg, TradeRoute
    from bot.strategies.base import Signal, TradeIntent

    engine = TradingEngine.__new__(TradingEngine)
    engine.settings = MagicMock(
        profit_only_mode=True,
        live_strict_profit=True,
        slippage_buffer_pct=0.0005,
    )
    engine._is_accumulation_intent = MagicMock(return_value=False)
    engine.risk = MagicMock()
    engine.risk.effective_min_net_profit.return_value = 0.0005

    intent = TradeIntent(
        from_asset="ETH",
        to_asset="ETH",
        reason="triangular loop",
        size_pct=0.05,
        edge=0.05,
        gross_return_pct=0.06,
        strategy_name="triangular_arbitrage",
    )
    route = TradeRoute(
        legs=tuple(
            RouteLeg(
                pair=PairInfo(symbol="ETH/USD", base="ETH", quote="USD"),
                side=Signal.SELL,
                from_asset="ETH",
                to_asset="USD",
            )
            for _ in range(4)
        )
    )
    reason = TradingEngine._live_mirror_offensive_block(engine, intent, route, 0.05)
    assert "4-leg offensive routes blocked" in reason
