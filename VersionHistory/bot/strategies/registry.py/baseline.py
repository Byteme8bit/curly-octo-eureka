"""Hot-swappable strategy plugin registry."""

from __future__ import annotations

import logging

from bot.strategies.base import Strategy
from bot.strategies.cross_momentum import CrossMomentumStrategy
from bot.strategies.hold import HoldStrategy
from bot.strategies.momentum_rotation import MomentumRotationStrategy
from bot.strategies.stat_arb import StatArbStrategy
from bot.strategies.triangular_arbitrage import TriangularArbitrageStrategy
from bot.orchestrator import StrategyOrchestrator
from config import Settings

logger = logging.getLogger(__name__)

STRATEGY_REGISTRY: dict[str, type[Strategy]] = {
    "cross_momentum": CrossMomentumStrategy,
    "triangular_arbitrage": TriangularArbitrageStrategy,
    "stat_arb": StatArbStrategy,
    "momentum_rotation": MomentumRotationStrategy,
    "hold": HoldStrategy,
}

DEFAULT_STRATEGIES = "cross_momentum,triangular_arbitrage,stat_arb"


def parse_strategy_names(raw: str | tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(raw, tuple):
        names = raw
    else:
        names = tuple(n.strip() for n in raw.split(",") if n.strip())
    unknown = [n for n in names if n not in STRATEGY_REGISTRY]
    if unknown:
        raise ValueError(f"Unknown strategies: {unknown}. Available: {list(STRATEGY_REGISTRY)}")
    return names


def build_strategies(settings: Settings) -> list[Strategy]:
    names = parse_strategy_names(settings.strategies)
    return [STRATEGY_REGISTRY[name](settings) for name in names]


def build_orchestrator(settings: Settings) -> StrategyOrchestrator:
    strategies = build_strategies(settings)
    logger.info("Loaded strategies: %s", ", ".join(s.name for s in strategies))
    return StrategyOrchestrator(strategies)
