"""Extended types for multi-strategy orchestration."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

import pandas as pd


class Signal(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class StrategyContext:
    """Optional multi-timeframe and market data passed to advanced strategies."""

    candles_by_timeframe: dict[str, dict[str, pd.DataFrame]] = field(default_factory=dict)
    pair_prices: dict[str, float] = field(default_factory=dict)
    allowed_strategies: frozenset[str] | None = None


@dataclass
class TradeIntent:
    from_asset: str
    to_asset: str
    reason: str
    size_pct: float
    edge: float
    is_defensive: bool = False
    is_accumulation: bool = False
    is_held_swap: bool = False
    is_expansion: bool = False
    require_leader_stable: bool = False
    strategy_name: str = ""
    gross_return_pct: float = 0.0
    # Optional pre-computed multi-leg route. When set (e.g. a closed
    # triangular-arbitrage loop A->B->C->A whose start == end), the engine
    # executes THIS route atomically instead of re-deriving a single-leg path
    # from from_asset/to_asset. This is what prevents the arb scanner from
    # firing only leg 1 and accumulating an intermediate coin (pure fee churn).
    route: object | None = None


@dataclass
class RotationOption:
    from_asset: str
    to_asset: str
    edge: float
    required_edge: float
    category: str  # "held_swap" | "expansion" | "leader_rotation" | "diversify" | "rotation"
    path: str = ""
    hops: int = 1


@dataclass
class StrategyResult:
    signals: dict[str, Signal]
    scores: dict[str, float]
    reasons: dict[str, str]
    sizes: dict[str, float]
    intents: list[TradeIntent] = field(default_factory=list)
    leader: str | None = None
    idle_reason: str = ""
    blocked: list[str] = field(default_factory=list)
    opportunities: list[RotationOption] = field(default_factory=list)


class Strategy(ABC):
    """Pluggable strategy interface — hot-swappable via registry."""

    name: str = "base"

    @abstractmethod
    def evaluate(
        self,
        candles: dict[str, pd.DataFrame],
        prices: dict[str, float],
        holdings: dict[str, float],
        risk=None,
        markets=None,
        context: StrategyContext | None = None,
    ) -> StrategyResult:
        """
        Args:
            candles: OHLCV per USD symbol (oldest first), primary timeframe
            prices: USD prices keyed by asset (ETH, ADA, ...)
            holdings: current balances keyed by asset
            context: optional multi-TF candles and cross-pair prices
        """
