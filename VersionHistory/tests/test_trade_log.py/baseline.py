"""Tests for trade gain/loss labeling."""

from __future__ import annotations

from bot.trade_log import pnl_label, pnl_label_for_trade


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
