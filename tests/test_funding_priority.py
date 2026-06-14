"""Tests for ADA-first funding preference (feature 051)."""
from __future__ import annotations

from bot.funding_priority import funding_rank
from bot.orchestrator import StrategyOrchestrator
from bot.strategies.base import TradeIntent
from config import load_settings


def test_funding_rank_prefers_ada_over_eth():
    preferred = ("ADA",)
    assert funding_rank("ADA", preferred) < funding_rank("ETH", preferred)
    assert funding_rank("USD", preferred) < funding_rank("ADA", preferred)


def test_orchestrator_tie_break_prefers_ada_source():
    settings = load_settings()
    orch = StrategyOrchestrator([], settings)
    ada_intent = TradeIntent(
        from_asset="ADA",
        to_asset="SOL",
        reason="test",
        size_pct=0.1,
        edge=0.01,
        strategy_name="cross_momentum",
    )
    eth_intent = TradeIntent(
        from_asset="ETH",
        to_asset="SOL",
        reason="test",
        size_pct=0.1,
        edge=0.01,
        strategy_name="cross_momentum",
    )

    def _rank(intent: TradeIntent) -> tuple:
        edge = intent.gross_return_pct or intent.edge
        return (
            edge,
            intent.is_defensive,
            -funding_rank(intent.from_asset, orch.preferred_start_assets),
        )

    ranked = sorted([eth_intent, ada_intent], key=_rank, reverse=True)
    assert ranked[0].from_asset == "ADA"
