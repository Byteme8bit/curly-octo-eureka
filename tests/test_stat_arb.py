"""Tests for stat-arb edge formula (feature 036).

Guards against the proxy formula `gross = abs(z) * 0.001` that mapped z=1.9 to
gross=0.0019, which sat *below* the 0.002 MIN_NET_PROFIT_PCT gate, causing all
real signals to be discarded.
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from bot.strategies.stat_arb import StatArbStrategy


def _settings(zscore_threshold=1.5, min_net_profit_pct=0.002, lookback=20):
    return SimpleNamespace(
        usd_symbols=["ETHUSD", "UNIUSD"],
        trade_size_pct=0.10,
        stat_arb_zscore_threshold=zscore_threshold,
        stat_arb_lookback=lookback,
        min_net_profit_pct=min_net_profit_pct,
        dust_usd=25.0,
        stat_arb_pairs=[("ETH", "UNI")],
    )


def _make_candles(prices_a, prices_b, symbol_a="ETHUSD", symbol_b="UNIUSD"):
    """Build minimal OHLCV DataFrames from close price lists."""
    def _df(prices):
        arr = pd.Series(prices, dtype=float)
        return pd.DataFrame({"open": arr, "high": arr, "low": arr, "close": arr, "volume": 1.0})

    return {symbol_a: _df(prices_a), symbol_b: _df(prices_b)}


def _candles_with_z(target_z: float, n: int = 30, base_ratio: float = 1.0, sigma: float = 0.02):
    """
    Construct close price series so the ratio close_a / close_b has a z-score
    of approximately `target_z` on the last bar.

    We fix close_b = 1.0 throughout, set the ratio mean = base_ratio, and place
    the last bar `target_z * sigma` above the mean.
    """
    rng = np.random.default_rng(42)
    # n-1 bars centred on base_ratio with controlled std
    ratios = rng.normal(loc=base_ratio, scale=sigma, size=n - 1).tolist()
    # last bar: shift to get the desired z-score
    mean_est = sum(ratios) / len(ratios)
    std_est = float(pd.Series(ratios).std())
    last_ratio = mean_est + target_z * std_est
    ratios.append(last_ratio)

    close_b = [1.0] * n
    close_a = [r * b for r, b in zip(ratios, close_b)]

    from config import ASSET_USD_SYMBOLS
    sym_a = ASSET_USD_SYMBOLS.get("ETH", "ETHUSD")
    sym_b = ASSET_USD_SYMBOLS.get("UNI", "UNIUSD")
    return _make_candles(close_a, close_b, sym_a, sym_b)


def test_stat_arb_edge_above_gate_at_z1_5():
    """z=1.5 with realistic σ must produce edge strictly above MIN_NET_PROFIT_PCT=0.002."""
    strat = StatArbStrategy(_settings(zscore_threshold=1.5, min_net_profit_pct=0.002))
    candles = _candles_with_z(target_z=1.6, sigma=0.02)  # slightly above threshold
    prices = {"ETH": 2000.0, "UNI": 10.0}
    holdings = {"ETH": 1.0, "UNI": 10.0}

    result = strat.evaluate(candles, prices, holdings)
    assert result.intents, (
        f"z≈1.6, σ=0.02 should produce an intent; blocked={result.blocked}"
    )
    edge = result.intents[0].edge
    assert edge > 0.002, f"edge {edge:.6f} should be > 0.002 (MIN_NET_PROFIT_PCT)"


def test_stat_arb_edge_capped_at_max():
    """Edge must never exceed 5% even for extreme z or σ."""
    strat = StatArbStrategy(_settings(zscore_threshold=1.0, min_net_profit_pct=0.0))
    # Very high z and σ
    candles = _candles_with_z(target_z=10.0, sigma=0.10)
    prices = {"ETH": 2000.0, "UNI": 10.0}
    holdings = {"ETH": 1.0, "UNI": 100.0}

    result = strat.evaluate(candles, prices, holdings)
    if result.intents:
        edge = result.intents[0].edge
        assert edge <= 0.05, f"edge {edge:.6f} must be capped at 0.05"


def test_stat_arb_below_threshold_no_intent():
    """When |z| < threshold no intent is emitted."""
    strat = StatArbStrategy(_settings(zscore_threshold=2.0))
    # z ≈ 1.0, well below threshold=2.0
    candles = _candles_with_z(target_z=1.0, sigma=0.02)
    prices = {"ETH": 2000.0, "UNI": 10.0}
    holdings = {"ETH": 1.0, "UNI": 10.0}

    result = strat.evaluate(candles, prices, holdings)
    assert not result.intents, "below-threshold signal must not emit an intent"


def test_stat_arb_insufficient_holding_blocked():
    """Insufficient from_asset holding must still block the trade."""
    strat = StatArbStrategy(_settings(zscore_threshold=1.5))
    candles = _candles_with_z(target_z=2.0, sigma=0.05)
    prices = {"ETH": 2000.0, "UNI": 10.0}
    # ETH is the overperformer (positive z → sell ETH, buy UNI).
    # Set ETH holding to 0 (below dust_usd=25).
    holdings = {"ETH": 0.0, "UNI": 0.0}

    result = strat.evaluate(candles, prices, holdings)
    assert not result.intents
    assert result.blocked, "insufficient holding should appear in blocked list"
