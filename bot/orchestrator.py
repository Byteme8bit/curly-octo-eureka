"""Multi-strategy orchestration — merges plugin outputs and ranks trade intents."""

from __future__ import annotations

import logging

import pandas as pd

from bot.strategies.base import Signal, Strategy, StrategyContext, StrategyResult, TradeIntent
from bot.funding_priority import funding_rank
from config import SYMBOL_ASSETS, Settings

logger = logging.getLogger(__name__)


class StrategyOrchestrator(Strategy):
    """Runs all enabled strategy plugins and merges their signals each tick."""

    name = "orchestrator"

    def __init__(self, strategies: list[Strategy], settings: Settings):
        self.strategies = strategies
        self.preferred_start_assets = settings.preferred_start_assets

    def evaluate(
        self,
        candles: dict[str, pd.DataFrame],
        prices: dict[str, float],
        holdings: dict[str, float],
        risk=None,
        markets=None,
        context: StrategyContext | None = None,
    ) -> StrategyResult:
        merged_signals: dict[str, Signal] = {}
        merged_scores: dict[str, float] = {}
        merged_reasons: dict[str, str] = {}
        merged_sizes: dict[str, float] = {}
        all_intents: list[TradeIntent] = []
        all_blocked: list[str] = []
        all_opportunities = []
        idle_parts: list[str] = []
        leader: str | None = None

        for strategy in self.strategies:
            if context and context.allowed_strategies is not None:
                if strategy.name not in context.allowed_strategies:
                    continue
            try:
                result = strategy.evaluate(
                    candles,
                    prices,
                    holdings,
                    risk=risk,
                    markets=markets,
                    context=context,
                )
            except Exception as exc:
                logger.exception("Strategy %s failed", strategy.name)
                all_blocked.append(f"{strategy.name} error: {exc}")
                continue

            merged_signals.update(result.signals)
            for symbol, score in result.scores.items():
                if symbol not in SYMBOL_ASSETS:
                    continue
                merged_scores[symbol] = max(merged_scores.get(symbol, score), score)
            merged_reasons.update(result.reasons)
            merged_sizes.update(result.sizes)

            for intent in result.intents:
                if not intent.strategy_name:
                    intent.strategy_name = strategy.name
                all_intents.append(intent)

            all_blocked.extend(f"[{strategy.name}] {b}" for b in result.blocked)
            all_opportunities.extend(result.opportunities)

            if result.leader:
                leader = result.leader
            if result.idle_reason and not result.intents:
                idle_parts.append(f"{strategy.name}: {result.idle_reason}")

        # Rank by gross return / edge — boost alternate strategies when adaptive mode is active
        adaptive = risk.adaptive_status().active if risk else False

        def _rank(intent: TradeIntent) -> tuple:
            edge = intent.gross_return_pct or intent.edge
            if adaptive and intent.strategy_name in (
                "stat_arb",
                "triangular_arbitrage",
                "cross_momentum",
            ):
                edge += 0.0005
            return (
                edge,
                intent.is_defensive,
                -funding_rank(intent.from_asset, self.preferred_start_assets),
            )

        all_intents.sort(key=_rank, reverse=True)

        return StrategyResult(
            signals=merged_signals,
            scores=merged_scores,
            reasons=merged_reasons,
            sizes=merged_sizes,
            intents=all_intents,
            leader=leader,
            idle_reason=" | ".join(idle_parts) if idle_parts else "",
            blocked=all_blocked,
            opportunities=all_opportunities,
        )
