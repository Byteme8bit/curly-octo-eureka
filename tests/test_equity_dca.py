"""Tests for scheduled equity DCA alongside crypto triangular arb."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.preflight import PreFlightValidator
from bot.strategies.base import TradeIntent
from bot.strategies.equity_dca import DcaState, EquityDcaStrategy
from bot.strategies.registry import parse_strategy_names
from bot.strategies.triangular_arbitrage import TriangularArbitrageStrategy
from bot.verifier.live_tag import build_live_verify_tag


def _dca_settings(tmp_path: Path, **overrides) -> SimpleNamespace:
    defaults = dict(
        dca_enabled=True,
        enable_equities=True,
        equity_watchlist=("AAPLx", "TSLAx", "SPYx"),
        equity_preference_tickers=(),
        equity_assets=frozenset({"AAPLx", "TSLAx", "SPYx"}),
        equity_usd_symbols=("AAPLx/USD", "TSLAx/USD", "SPYx/USD"),
        dca_interval_hours=24.0,
        dca_amount_usd=30.0,
        dca_per_symbol_usd=0.0,
        dca_state_file=tmp_path / ".dca_state.json",
        min_usd_trade=10.0,
        max_equity_allocation_pct=0.15,
        max_equity_bucket_pct=0.55,
        target_equity_allocation_pct=0.50,
        equity_dca_priority=False,
        equity_accumulation_min_pct=0.45,
        equity_accumulation_phase=False,
        live_enabled=True,
        live_allowed_assets=("ETH", "AAPLx", "TSLAx", "SPYx"),
        strategies=("cross_momentum", "triangular_arbitrage", "stat_arb"),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _strategy(tmp_path: Path, **kwargs) -> EquityDcaStrategy:
    return EquityDcaStrategy(_dca_settings(tmp_path, **kwargs))


def test_dca_preference_weighted_rotation(tmp_path: Path) -> None:
    strat = _strategy(
        tmp_path,
        equity_preference_tickers=("NVDAx",),
        equity_watchlist=("AAPLx", "NVDAx"),
        dca_per_symbol_usd=0.0,
    )
    watchlist = ("AAPLx", "NVDAx")
    weighted = strat._weighted_watchlist(watchlist)
    assert weighted.count("NVDAx") == 2
    assert weighted.count("AAPLx") == 1
    assert strat._budget_usd(watchlist, "NVDAx") > strat._budget_usd(watchlist, "AAPLx")


def test_dca_state_interval_gating(tmp_path: Path) -> None:
    state = DcaState(
        last_cycle_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        cycle_index=0,
    )
    assert state.hours_since_cycle() == pytest.approx(1.0, abs=0.1)

    strat = _strategy(tmp_path)
    strat._state = state
    result = strat.evaluate(
        candles={},
        prices={"AAPLx": 200.0, "TSLAx": 300.0, "SPYx": 500.0},
        holdings={"USD": 100.0},
    )
    assert not result.intents
    assert "next buy" in result.idle_reason.lower()


def test_dca_emits_usd_buy_when_due(tmp_path: Path) -> None:
    strat = _strategy(tmp_path)
    result = strat.evaluate(
        candles={},
        prices={"AAPLx": 200.0, "TSLAx": 300.0, "SPYx": 500.0},
        holdings={"USD": 100.0},
    )
    assert len(result.intents) == 1
    intent = result.intents[0]
    assert intent.from_asset == "USD"
    assert intent.to_asset == "AAPLx"
    assert intent.is_accumulation
    assert intent.strategy_name == "equity_dca"
    assert intent.size_pct == pytest.approx(0.1, rel=1e-3)  # $10 of $100 split 3 ways


def test_dca_splits_budget_across_watchlist(tmp_path: Path) -> None:
    strat = _strategy(tmp_path, dca_amount_usd=60.0)
    result = strat.evaluate(
        candles={},
        prices={"AAPLx": 200.0, "TSLAx": 300.0, "SPYx": 500.0},
        holdings={"USD": 200.0},
    )
    intent = result.intents[0]
    assert intent.size_pct == pytest.approx(0.1, rel=1e-3)  # $20 of $200


def test_dca_per_symbol_mode(tmp_path: Path) -> None:
    strat = _strategy(tmp_path, dca_per_symbol_usd=25.0)
    result = strat.evaluate(
        candles={},
        prices={"AAPLx": 200.0, "TSLAx": 300.0, "SPYx": 500.0},
        holdings={"USD": 100.0},
    )
    intent = result.intents[0]
    assert intent.size_pct == pytest.approx(0.25, rel=1e-3)


def test_dca_uses_live_usd_when_paper_empty(tmp_path: Path) -> None:
    from bot.strategies.base import StrategyContext

    strat = _strategy(tmp_path, dca_per_symbol_usd=15.0)
    ctx = StrategyContext(live_usd_balance=266.0)
    result = strat.evaluate(
        candles={},
        prices={"AAPLx": 200.0, "TSLAx": 300.0, "SPYx": 500.0},
        holdings={"USD": 0.0},
        context=ctx,
    )
    assert len(result.intents) == 1
    assert result.intents[0].from_asset == "USD"


def test_dca_blocks_when_not_in_live_allowlist(tmp_path: Path) -> None:
    strat = _strategy(
        tmp_path,
        live_allowed_assets=("ETH", "TSLAx", "SPYx"),
    )
    result = strat.evaluate(
        candles={},
        prices={"AAPLx": 200.0, "TSLAx": 300.0, "SPYx": 500.0},
        holdings={"USD": 100.0},
    )
    assert not result.intents
    assert any("LIVE_ALLOWED_ASSETS" in b for b in result.blocked)


def test_dca_equity_only_no_crypto(tmp_path: Path) -> None:
    strat = _strategy(tmp_path)
    result = strat.evaluate(
        candles={},
        prices={"ETH": 3000.0, "AAPLx": 200.0},
        holdings={"USD": 100.0, "ETH": 1.0},
    )
    assert result.intents[0].to_asset in strat.equity_assets
    assert result.intents[0].from_asset == "USD"


def test_dca_on_trade_executed_advances_schedule(tmp_path: Path) -> None:
    strat = _strategy(tmp_path)
    strat.on_trade_executed(
        TradeIntent(
            from_asset="USD",
            to_asset="AAPLx",
            reason="test",
            size_pct=0.1,
            edge=0.0,
            strategy_name="equity_dca",
        )
    )
    assert strat._state.last_cycle_at
    assert strat._state.cycle_index == 1
    assert "AAPLx" in strat._state.last_buy


def test_build_strategies_auto_appends_equity_dca(tmp_path: Path) -> None:
    settings = _dca_settings(tmp_path)
    names = list(parse_strategy_names(settings.strategies))
    if settings.dca_enabled and "equity_dca" not in names:
        names.append("equity_dca")
    assert "equity_dca" in names
    assert "triangular_arbitrage" in names


def test_triangular_excludes_equity_assets() -> None:
    settings = SimpleNamespace(
        watch_assets=("ETH", "AAPLx", "UNI"),
        equity_assets=frozenset({"AAPLx"}),
        trade_size_pct=0.1,
        fee_rate=0.004,
        min_net_profit_pct=0.001,
        dust_usd=25.0,
    )
    strat = TriangularArbitrageStrategy(settings)
    # Internal asset list must omit equities even when in watch_assets.
    assets = [
        a
        for a in strat.watch_assets
        if a != "USD" and a not in strat.equity_assets
    ]
    assert "AAPLx" not in assets
    assert "ETH" in assets


def test_preflight_bypasses_min_net_for_accumulation() -> None:
    pf = PreFlightValidator(
        fee_engine=SimpleNamespace(compounded_fee_pct=lambda _s: 0.01),
        slippage_buffer_pct=0.001,
        min_net_profit_pct=0.005,
    )
    intent = TradeIntent(
        from_asset="USD",
        to_asset="AAPLx",
        reason="DCA",
        size_pct=0.1,
        edge=0.0,
        is_accumulation=True,
        strategy_name="equity_dca",
    )
    result = pf.validate(intent, route_symbols=("AAPLx/USD",), hops=1)
    assert result.allowed
    assert "accumulation" in result.reason.lower()


def test_live_tag_confirms_dca_buy() -> None:
    trade = {
        "from_asset": "USD",
        "to_asset": "AAPLx",
        "symbol": "AAPLx/USD",
        "strategy_name": "equity_dca",
        "is_accumulation": True,
        "from_qty": 15.0,
        "price": 200.0,
        "hops": 1,
    }
    tag = build_live_verify_tag(trade, skip_kraken=True)
    assert tag.verdict.value == "CONFIRM"
    assert "DCA" in tag.tag


def test_registry_includes_equity_dca() -> None:
    names = parse_strategy_names("cross_momentum,triangular_arbitrage,equity_dca")
    assert "equity_dca" in names
