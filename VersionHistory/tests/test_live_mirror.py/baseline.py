"""Tests for LIVE_MIRROR_PAPER paper-shadow + live mirror mode."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bot.engine import TradingEngine
from bot.live_broker import LiveBroker
from bot.markets import PairInfo, RouteLeg, TradeRoute
from bot.paper_broker import PaperBroker
from bot.strategies.base import Signal, TradeIntent
from config import load_settings


class _StubExchange:
    def __init__(self) -> None:
        self.balances = {"ETH": 1.0, "USD": 100.0}
        self.orders: list[dict] = []

    def fetch_balance(self):
        return {"total": dict(self.balances)}

    def market(self, symbol: str):
        return {"limits": {"amount": {"min": 0.0001}}}

    def amount_to_precision(self, symbol: str, amount: float) -> str:
        return f"{amount:.6f}"

    def create_order(self, symbol, order_type, side, amount):
        order = {
            "id": f"oid-{len(self.orders)}",
            "symbol": symbol,
            "status": "closed",
            "filled": float(amount),
            "average": 3000.0,
            "fee": {"cost": float(amount) * 3000.0 * 0.0026, "currency": "USD"},
            "fees": [],
        }
        self.orders.append(order)
        return order

    def fetch_order(self, order_id, symbol):
        return self.orders[-1]


@pytest.fixture
def mirror_engine(tmp_path: Path) -> TradingEngine:
    engine = TradingEngine.__new__(TradingEngine)
    engine._mirror_mode = True
    engine._live_mode = True
    engine.settings = MagicMock(
        live_min_eth_reserve=0.5,
        live_max_trades=3,
        live_max_usd_per_trade=500.0,
        live_allowed_assets=("ETH", "ADA"),
        live_allow_triangular=False,
        live_max_route_legs=1,
        discord_enabled=False,
    )
    engine.markets = MagicMock()
    engine.preflight = MagicMock()
    engine.preflight.validate.return_value = MagicMock(allowed=True, net_return_pct=0.01)
    engine.risk = MagicMock()
    engine.risk.path_edge.return_value = 0.002
    engine.risk.effective_min_net_profit.return_value = 0.0
    engine.receipts = MagicMock()
    engine.receipts.save.return_value = tmp_path / "r.txt"
    engine.auditor = MagicMock()
    engine.discord = MagicMock()

    paper = PaperBroker(
        initial_balances={"ETH": 1.0, "USD": 0.0},
        fee_rate=0.0026,
        state_file=tmp_path / "paper.json",
    )
    live = LiveBroker(
        exchange=_StubExchange(),
        fee_rate=0.0026,
        state_file=tmp_path / "live.json",
        min_usd_trade=10.0,
        max_usd_per_trade=500.0,
        allowed_assets=("ETH", "ADA"),
        allow_triangular=False,
        max_route_legs=1,
    )
    engine.broker = paper
    engine.paper_broker = paper
    engine.live_broker = live
    engine._live_constraints = MagicMock()
    engine._live_constraints.validate_intent.return_value = MagicMock(
        allowed=True, size_pct=0.1, reason=""
    )
    engine._live_constraints.check_route_eth_floor.return_value = MagicMock(
        allowed=True, reason=""
    )
    return engine


def test_config_mirror_keeps_paper_state_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVE_ENABLED", "1")
    monkeypatch.setenv("LIVE_MIRROR_PAPER", "1")
    settings = load_settings()
    assert settings.live_mirror_paper is True
    assert settings.state_file.name == ".paper_state.json"
    assert settings.live_state_file.name == ".live_state.json"


def test_mirror_skips_when_live_halted(mirror_engine: TradingEngine) -> None:
    mirror_engine.live_broker.halt("test")
    intent = TradeIntent(
        from_asset="ETH",
        to_asset="USD",
        reason="test",
        size_pct=0.1,
        edge=0.01,
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
    result = mirror_engine._mirror_intent_to_live(
        intent,
        route,
        {"ETH/USD": 3000.0},
        {"ETH": 3000.0},
        paper_size_pct=0.1,
    )
    assert result is None
    assert mirror_engine.live_broker.exchange.orders == []


def test_mirror_executes_when_gates_pass(mirror_engine: TradingEngine) -> None:
    intent = TradeIntent(
        from_asset="ETH",
        to_asset="USD",
        reason="profitable paper trade",
        size_pct=0.1,
        edge=0.01,
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
    with patch.object(mirror_engine, "_after_live_trade") as after_live:
        result = mirror_engine._mirror_intent_to_live(
            intent,
            route,
            {"ETH/USD": 3000.0},
            {"ETH": 3000.0},
            paper_size_pct=0.1,
        )
    assert result is not None
    assert result.get("live") is True
    after_live.assert_called_once()
    assert mirror_engine.live_broker.exchange.orders


def test_mirror_skips_when_live_preflight_blocks(mirror_engine: TradingEngine) -> None:
    mirror_engine.preflight.validate.return_value = MagicMock(
        allowed=False, reason="net profit too low"
    )
    intent = TradeIntent(
        from_asset="ETH",
        to_asset="USD",
        reason="test",
        size_pct=0.1,
        edge=0.01,
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
    result = mirror_engine._mirror_intent_to_live(
        intent,
        route,
        {"ETH/USD": 3000.0},
        {"ETH": 3000.0},
        paper_size_pct=0.1,
    )
    assert result is None
    assert mirror_engine.live_broker.exchange.orders == []


def test_execute_intent_runs_paper_then_mirror(mirror_engine: TradingEngine) -> None:
    intent = TradeIntent(
        from_asset="ETH",
        to_asset="USD",
        reason="cross",
        size_pct=0.05,
        edge=0.01,
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
    mirror_engine.markets.find_path.return_value = route
    mirror_engine._pair_price = MagicMock(return_value=3000.0)
    with patch.object(mirror_engine, "_mirror_intent_to_live", return_value={"live": True}) as mirror:
        trade = mirror_engine._execute_intent(intent, {"ETH": 3000.0})
    assert trade is not None
    assert mirror_engine.broker.balance("ETH") < 1.0
    mirror.assert_called_once()
    assert trade.get("live_mirrored") is True
