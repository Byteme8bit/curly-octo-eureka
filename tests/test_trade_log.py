"""Tests for trade gain/loss labeling."""

from __future__ import annotations

from bot.trade_log import (
    classify_trade,
    pnl_label,
    pnl_label_for_trade,
    trade_rationale,
)


def test_usd_buy_with_zero_gain_is_entry():
    assert pnl_label(0.0, "buy", "usd") == "$0.00 (entry)"


def test_cross_buy_with_fee_loss_shows_loss_not_entry():
    assert pnl_label(-0.25, "buy", "cross") == "-$0.25 (loss)"


def test_cross_buy_break_even_shows_swap():
    assert pnl_label(0.0, "buy", "cross") == "$0.00 (swap)"


def test_sell_profit():
    assert pnl_label(1.58, "sell", "cross") == "+$1.58 (profit)"


def test_multi_hop_uses_gain_not_entry():
    trade = {
        "side": "buy",
        "type": "multi_hop",
        "gain_loss": 2.5,
    }
    assert pnl_label_for_trade(trade) == "+$2.50 (profit)"


def test_pnl_label_for_trade_passes_type():
    trade = {
        "side": "buy",
        "type": "cross",
        "gain_loss": -0.19,
    }
    assert pnl_label_for_trade(trade) == "-$0.19 (loss)"


def test_classify_defensive_is_loss_mitigation():
    assert classify_trade({"is_defensive": True}).startswith("LOSS-MITIGATION")


def test_classify_profitable_usd_sell_is_profit_taking():
    trade = {"side": "sell", "to_asset": "USD", "gain_loss": 5.0}
    assert classify_trade(trade).startswith("PROFIT-TAKING")


def test_classify_losing_usd_sell_is_loss_mitigation():
    trade = {"side": "sell", "to_asset": "USD", "gain_loss": -3.0}
    assert classify_trade(trade).startswith("LOSS-MITIGATION")


def test_classify_expansion_is_growth():
    assert classify_trade({"is_expansion": True}).startswith("GROWTH")


def test_classify_held_swap_is_rebalance():
    assert classify_trade({"is_held_swap": True}).startswith("REBALANCE")


def test_trade_rationale_surfaces_why_strategy_and_edge():
    trade = {
        "is_expansion": True,
        "strategy_name": "cross_momentum",
        "gross_return_pct": 0.0125,
        "reason": "15m EMA crossover with rising RVOL",
        "from_asset": "USD",
        "to_asset": "SOL",
    }
    text = trade_rationale(trade)
    assert "Why: GROWTH" in text
    assert "`cross_momentum`" in text
    assert "+1.25%" in text
    assert "15m EMA crossover" in text


def test_trade_rationale_handles_missing_edge():
    trade = {"is_defensive": True, "strategy_name": "stat_arb"}
    text = trade_rationale(trade)
    assert "LOSS-MITIGATION" in text
    assert "Expected edge" not in text
