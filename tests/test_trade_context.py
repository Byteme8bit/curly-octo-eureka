"""Tests for news + market-flow trade context gates."""

from __future__ import annotations

import pandas as pd

from bot.auditor.news_client import NewsHeadline
from bot.preflight import PreFlightValidator
from bot.fee_engine import FeeEngine
from bot.strategies.base import TradeIntent
from bot.trade_context import TradeContextChecker, compute_market_flow


def _candles(*, weak: bool) -> dict[str, pd.DataFrame]:
    rows = []
    for _ in range(10):
        rows.append({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0})
    if weak:
        rows.append({"open": 100.0, "high": 100.5, "low": 98.0, "close": 98.5, "volume": 1.0})
    else:
        rows.append({"open": 100.0, "high": 102.0, "low": 99.5, "close": 101.5, "volume": 1.0})
    df = pd.DataFrame(rows)
    return {
        "ETH/USD": df,
        "BTC/USD": df,
        "SOL/USD": df,
        "ADA/USD": df,
    }


def _checker(**overrides) -> TradeContextChecker:
    defaults = dict(
        news_check_enabled=True,
        news_block_severe=True,
        news_block_dca=False,
        flow_check_enabled=True,
        flow_momentum_threshold=-0.008,
        flow_risk_off_ratio=0.55,
        news_enabled=True,
        news_provider="rss",
        cryptopanic_api_key="",
        rss_feeds="",
        news_max_items=5,
        watch_assets=("ETH", "BTC", "SOL"),
        symbol_assets={"ETH/USD": "ETH", "BTC/USD": "BTC", "SOL/USD": "SOL", "ADA/USD": "ADA"},
    )
    defaults.update(overrides)
    return TradeContextChecker(**defaults)


def test_compute_market_flow_risk_off():
    flow = compute_market_flow(
        _candles(weak=True),
        {"ETH/USD": "ETH", "BTC/USD": "BTC", "SOL/USD": "SOL", "ADA/USD": "ADA"},
        momentum_threshold=-0.008,
        risk_off_ratio=0.55,
    )
    assert flow.regime == "risk_off"
    assert flow.negative_ratio >= 0.55


def test_severe_news_blocks_offensive_intent():
    checker = _checker()
    checker._headlines = [
        NewsHeadline(
            title="Bitcoin crash wipes billions as liquidations spike",
            url="https://example.com/1",
            published_at="2026-06-15T12:00:00Z",
            source="test",
            tickers=["BTC"],
            sentiment="negative",
        )
    ]
    intent = TradeIntent(
        from_asset="USD",
        to_asset="BTC",
        reason="momentum",
        size_pct=0.1,
        edge=0.01,
        gross_return_pct=0.01,
        strategy_name="cross_momentum",
    )
    gate = checker.check_intent(intent)
    assert not gate.allowed
    assert "News gate" in gate.reason


def test_dca_not_blocked_by_news_by_default():
    checker = _checker()
    checker._headlines = [
        NewsHeadline(
            title="Ethereum selloff accelerates",
            url="https://example.com/2",
            published_at="2026-06-15T12:00:00Z",
            source="test",
            tickers=["ETH"],
            sentiment="negative",
        )
    ]
    intent = TradeIntent(
        from_asset="USD",
        to_asset="AAPLx",
        reason="scheduled dca",
        size_pct=0.05,
        edge=0.0,
        gross_return_pct=0.0,
        strategy_name="equity_dca",
        is_accumulation=True,
    )
    assert checker.check_intent(intent).allowed


def test_whale_follow_bypasses_news_and_flow():
    checker = _checker()
    checker._headlines = [
        NewsHeadline(
            title="ETH hack drains exchange",
            url="https://example.com/3",
            published_at="2026-06-15T12:00:00Z",
            source="test",
            tickers=["ETH"],
            sentiment="negative",
        )
    ]
    checker.refresh(_candles(weak=True))
    intent = TradeIntent(
        from_asset="USD",
        to_asset="ETH",
        reason="whale-follow buy ETH",
        size_pct=0.12,
        edge=0.008,
        gross_return_pct=0.008,
        strategy_name="whale_follow",
    )
    assert checker.check_intent(intent).allowed


def test_risk_off_flow_blocks_offensive_buy():
    checker = _checker()
    checker.refresh(_candles(weak=True))
    intent = TradeIntent(
        from_asset="USD",
        to_asset="SOL",
        reason="stat_arb",
        size_pct=0.1,
        edge=0.01,
        gross_return_pct=0.01,
        strategy_name="stat_arb",
    )
    gate = checker.check_intent(intent)
    assert not gate.allowed
    assert "Market flow risk-off" in gate.reason


def test_whale_follow_positive_edge_passes_preflight():
    """Whale follow still requires net > fees + slippage buffer."""
    gross = 0.012
    pf = PreFlightValidator(
        FeeEngine(None, 0.004, force_static=True),
        slippage_buffer_pct=0.0005,
        min_net_profit_pct=0.0005,
    )
    intent = TradeIntent(
        from_asset="USD",
        to_asset="ETH",
        reason="whale-follow",
        size_pct=0.15,
        edge=gross,
        gross_return_pct=gross,
        strategy_name="whale_follow",
    )
    res = pf.validate(intent, route_symbols=("ETH/USD",), hops=1, min_net_profit=0.0005)
    assert res.allowed
    assert res.net_return_pct > 0


def test_net_negative_after_fees_blocked():
    pf = PreFlightValidator(
        FeeEngine(None, 0.004, force_static=True),
        slippage_buffer_pct=0.0005,
        min_net_profit_pct=0.0005,
    )
    intent = TradeIntent(
        from_asset="ETH",
        to_asset="SOL",
        reason="triangular",
        size_pct=0.1,
        edge=0.002,
        gross_return_pct=0.002,
        strategy_name="triangular_arbitrage",
    )
    res = pf.validate(intent, route_symbols=("ETH/USD",), hops=1)
    assert not res.allowed
    assert res.net_return_pct < 0
