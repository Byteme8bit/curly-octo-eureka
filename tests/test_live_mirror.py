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
from bot.verifier.live_tag import LiveVerifyResult
from bot.verifier.models import Verdict
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


def _sample_paper_trade() -> dict:
    return {
        "from_asset": "ETH",
        "to_asset": "USD",
        "symbol": "ETH/USD",
        "edge": 0.01,
        "gross_return_pct": 0.01,
        "hops": 1,
        "reason": "test",
    }


def _sample_intent_route():
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
    return intent, route


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
        live_mirror_min_confidence="confirm",
        live_mirror_uncertain=False,
        live_mirror_skip_log_file=tmp_path / "mirror_skips.log",
        trade_verify_skip_kraken=True,
        profit_only_mode=False,
        crypto_day_trade_mode=False,
        crypto_min_trade_edge=0.0,
        equity_assets=(),
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
    engine.fee_engine = MagicMock()
    engine._live_kraken = None

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
    engine._after_live_trade = MagicMock()
    return engine


def test_config_mirror_keeps_paper_state_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVE_ENABLED", "1")
    monkeypatch.setenv("LIVE_MIRROR_PAPER", "1")
    settings = load_settings()
    assert settings.live_mirror_paper is True
    assert settings.state_file.name == ".paper_state.json"
    assert settings.live_state_file.name == ".live_state.json"
    assert settings.live_mirror_min_confidence == "confirm"


def test_mirror_skips_when_live_halted(mirror_engine: TradingEngine) -> None:
    mirror_engine.live_broker.halt("test")
    intent, route = _sample_intent_route()
    with patch.object(
        mirror_engine,
        "_live_verify_result",
        return_value=LiveVerifyResult(tag="ok", verdict=Verdict.CONFIRM),
    ):
        result = mirror_engine._mirror_intent_to_live(
            intent,
            route,
            {"ETH/USD": 3000.0},
            {"ETH": 3000.0},
            paper_size_pct=0.1,
            paper_trade=_sample_paper_trade(),
        )
    assert result is None
    assert mirror_engine.live_broker.exchange.orders == []


def test_mirror_executes_on_confirm_verdict(mirror_engine: TradingEngine) -> None:
    intent, route = _sample_intent_route()
    with patch.object(
        mirror_engine,
        "_live_verify_result",
        return_value=LiveVerifyResult(
            tag="✓ Live-viable est. net +$1.00 after fees",
            verdict=Verdict.CONFIRM,
        ),
    ):
        result = mirror_engine._mirror_intent_to_live(
            intent,
            route,
            {"ETH/USD": 3000.0},
            {"ETH": 3000.0},
            paper_size_pct=0.1,
            paper_trade=_sample_paper_trade(),
        )
    assert result is not None
    assert result.get("live") is True
    mirror_engine._after_live_trade.assert_called_once()
    assert mirror_engine.live_broker.exchange.orders


def test_mirror_skips_on_deny_verdict(mirror_engine: TradingEngine) -> None:
    intent, route = _sample_intent_route()
    with patch.object(
        mirror_engine,
        "_live_verify_result",
        return_value=LiveVerifyResult(
            tag="✗ Would likely fail live: net profit too low",
            verdict=Verdict.DENY,
        ),
    ):
        result = mirror_engine._mirror_intent_to_live(
            intent,
            route,
            {"ETH/USD": 3000.0},
            {"ETH": 3000.0},
            paper_size_pct=0.1,
            paper_trade=_sample_paper_trade(),
        )
    assert result is None
    assert mirror_engine.live_broker.exchange.orders == []
    skip_log = mirror_engine.settings.live_mirror_skip_log_file
    assert skip_log.exists()
    assert "live_tag DENY" in skip_log.read_text(encoding="utf-8")


def test_mirror_bypasses_preflight_on_confirm(mirror_engine: TradingEngine) -> None:
    # Negative net is blocked by _live_mirror_offensive_block even on CONFIRM;
    # use allowed=False with positive net to exercise preflight bypass only.
    mirror_engine.preflight.validate.return_value = MagicMock(
        allowed=False, reason="net profit too low", net_return_pct=0.01
    )
    intent, route = _sample_intent_route()
    with patch.object(
        mirror_engine,
        "_live_verify_result",
        return_value=LiveVerifyResult(tag="ok", verdict=Verdict.CONFIRM),
    ):
        result = mirror_engine._mirror_intent_to_live(
            intent,
            route,
            {"ETH/USD": 3000.0},
            {"ETH": 3000.0},
            paper_size_pct=0.1,
            paper_trade=_sample_paper_trade(),
        )
    assert result is not None
    assert mirror_engine.live_broker.exchange.orders


def test_uncertain_triangular_skipped_without_triangular(
    mirror_engine: TradingEngine,
) -> None:
    mirror_engine.settings.live_mirror_min_confidence = "uncertain_ok"
    mirror_engine.settings.live_mirror_uncertain = True
    intent, route = _sample_intent_route()
    paper_trade = {
        **_sample_paper_trade(),
        "type": "multi_hop",
        "hops": 3,
        "reason": "triangular leg 1/3",
    }
    with patch.object(
        mirror_engine,
        "_live_verify_result",
        return_value=LiveVerifyResult(
            tag="⚠ Paper-only / multi-hop — live execution uncertain",
            verdict=Verdict.UNCERTAIN,
        ),
    ):
        result = mirror_engine._mirror_intent_to_live(
            intent,
            route,
            {"ETH/USD": 3000.0},
            {"ETH": 3000.0},
            paper_size_pct=0.1,
            paper_trade=paper_trade,
        )
    assert result is None
    assert "LIVE_ALLOW_TRIANGULAR" in mirror_engine.settings.live_mirror_skip_log_file.read_text(
        encoding="utf-8"
    )


def test_uncertain_triangular_mirrors_when_allowed(
    mirror_engine: TradingEngine,
) -> None:
    mirror_engine.settings.live_mirror_min_confidence = "uncertain_ok"
    mirror_engine.settings.live_mirror_uncertain = True
    mirror_engine.settings.live_allow_triangular = True
    mirror_engine.live_broker.allow_triangular = True
    mirror_engine.live_broker.max_route_legs = 3
    intent, route = _sample_intent_route()
    paper_trade = {
        **_sample_paper_trade(),
        "type": "multi_hop",
        "hops": 3,
    }
    with patch.object(
        mirror_engine,
        "_live_verify_result",
        return_value=LiveVerifyResult(
            tag="⚠ Paper-only / multi-hop — live execution uncertain",
            verdict=Verdict.UNCERTAIN,
        ),
    ):
        result = mirror_engine._mirror_intent_to_live(
            intent,
            route,
            {"ETH/USD": 3000.0},
            {"ETH": 3000.0},
            paper_size_pct=0.1,
            paper_trade=paper_trade,
        )
    assert result is not None
    assert mirror_engine.live_broker.exchange.orders


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
