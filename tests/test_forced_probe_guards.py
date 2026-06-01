from __future__ import annotations

from types import SimpleNamespace

from bot.engine import TradingEngine
from bot.portfolio_constraints import PortfolioConstraints
from bot.strategies.base import TradeIntent


class _Runtime:
    def is_trading_active(self) -> bool:
        return True


class _Risk:
    def __init__(self, *, allowed: bool = True):
        self.allowed = allowed
        self.recorded = False

    def can_trade_now(self):
        return SimpleNamespace(allowed=self.allowed, reason="paused")

    def idle_hours(self) -> float:
        return 24.0

    def path_edge(self, hops: int, *, is_held_swap: bool = False) -> float:
        return 0.005

    def record_trade(self) -> None:
        self.recorded = True


class _Markets:
    def find_path(self, from_asset: str, to_asset: str):
        return SimpleNamespace(hops=1, symbols=[f"{from_asset}/{to_asset}"])


def _engine(*, risk_allowed: bool = True) -> TradingEngine:
    engine = object.__new__(TradingEngine)
    engine.settings = SimpleNamespace(
        idle_probe_force_minutes=1.0,
        idle_probe_size_pct=0.05,
        min_eth_reserve=0.25,
        discord_enabled=False,
    )
    engine.runtime = _Runtime()
    engine.risk = _Risk(allowed=risk_allowed)
    engine.markets = _Markets()
    engine.constraints = PortfolioConstraints(
        min_eth_reserve=0.25,
        max_alt_allocation_pct=0.40,
        min_usd_trade=10.0,
    )
    engine._last_probe_monotonic = -1_000_000_000.0
    engine.governor = SimpleNamespace(record_trade=lambda *args, **kwargs: None)
    engine.auditor = SimpleNamespace(note_trade=lambda *args, **kwargs: None)
    engine.discord = SimpleNamespace(post_important=lambda *args, **kwargs: None)
    engine.receipts = SimpleNamespace(save=lambda trade: "receipt.json")
    return engine


def _intent(**overrides) -> TradeIntent:
    return TradeIntent(
        from_asset=overrides.get("from_asset", "ETH"),
        to_asset=overrides.get("to_asset", "ADA"),
        reason=overrides.get("reason", "strategy candidate"),
        size_pct=overrides.get("size_pct", 0.05),
        edge=overrides.get("edge", 0.10),
        gross_return_pct=overrides.get("gross_return_pct", 0.10),
        strategy_name=overrides.get("strategy_name", "stat_arb"),
    )


def test_forced_probe_honors_risk_gate_before_executing():
    engine = _engine(risk_allowed=False)
    executed: list[TradeIntent] = []
    engine._execute_intent = lambda intent, prices: executed.append(intent) or {"ok": True}

    engine._maybe_force_probe(
        [_intent()],
        SimpleNamespace(opportunities=[]),
        {"ETH": 1.0, "ADA": 100.0, "USD": 0.0},
        {"ETH": 2000.0, "ADA": 0.50},
        2050.0,
        [],
    )

    assert executed == []
    assert not engine.risk.recorded


def test_forced_probe_honors_alt_allocation_cap_before_executing():
    engine = _engine(risk_allowed=True)
    executed: list[TradeIntent] = []
    engine._execute_intent = lambda intent, prices: executed.append(intent) or {"ok": True}

    engine._maybe_force_probe(
        [_intent()],
        SimpleNamespace(opportunities=[]),
        {"ETH": 1.0, "ADA": 3000.0, "USD": 0.0},
        {"ETH": 2000.0, "ADA": 0.50},
        3500.0,
        [],
    )

    assert executed == []
    assert not engine.risk.recorded
