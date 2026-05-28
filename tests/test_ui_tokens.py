"""Tests for the centralized UI tokens module."""
from __future__ import annotations

from bot.ui_tokens import (
    ASSET_FALLBACK,
    ASSET_PALETTE,
    DISCORD,
    TerminalToken,
    asset_color,
    colorize,
    pnl_color,
)


def test_asset_color_known():
    assert asset_color("ETH") == ASSET_PALETTE["ETH"]
    assert asset_color("BTC") == ASSET_PALETTE["BTC"]


def test_asset_color_case_insensitive():
    assert asset_color("eth") == ASSET_PALETTE["ETH"]


def test_asset_color_fallback():
    assert asset_color("XYZ_UNKNOWN") == ASSET_FALLBACK


def test_colorize_wraps_and_resets():
    out = colorize("hello", TerminalToken.SUCCESS)
    assert "hello" in out
    assert out.startswith(TerminalToken.SUCCESS)
    assert out.endswith(TerminalToken.RESET)


def test_pnl_color_positive():
    assert pnl_color(10.0) == TerminalToken.POSITIVE
    assert pnl_color(0.0) == TerminalToken.POSITIVE


def test_pnl_color_negative():
    assert pnl_color(-0.01) == TerminalToken.NEGATIVE


def test_discord_colors_are_integers():
    for name in ("SUCCESS", "ERROR", "WARNING", "INFO", "BUY", "SELL"):
        value = getattr(DISCORD, name)
        assert isinstance(value, int)
        assert 0 <= value <= 0xFFFFFF


def test_discord_colors_distinct():
    palette = {
        DISCORD.SUCCESS,
        DISCORD.ERROR,
        DISCORD.WARNING,
        DISCORD.INFO,
        DISCORD.HEARTBEAT,
        DISCORD.HIBERNATING,
    }
    # All six should be unique
    assert len(palette) == 6
