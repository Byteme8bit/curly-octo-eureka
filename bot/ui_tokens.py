"""Centralized UI style tokens.

Single source of truth for colors and text styles used across:

* Terminal output (`bot/display.py`) — colorama ANSI strings.
* Discord embeds (future use in `bot/discord_bot.py`) — integer RGB.

When you need a color, import a constant or a helper from this module rather
than reaching for `colorama.Fore` or a raw hex literal. See
`docs/design/color-tokens.md` for the design rationale.
"""
from __future__ import annotations

from dataclasses import dataclass

from colorama import Fore, Style


# ---------------------------------------------------------------------------
# Semantic terminal tokens
# ---------------------------------------------------------------------------
# Use these by *meaning*, not by *color name*. If we ever recolor the whole UI
# we only touch this file.

class TerminalToken:
    """ANSI escape sequences keyed by semantic role."""

    # State + outcome
    SUCCESS = Fore.GREEN
    ERROR = Fore.RED
    WARNING = Fore.YELLOW
    INFO = Fore.CYAN
    MUTED = Fore.LIGHTBLACK_EX
    EMPHASIS = Fore.WHITE + Style.BRIGHT

    # Trading directions
    BUY = Fore.GREEN
    SELL = Fore.RED
    HOLD = Fore.LIGHTBLACK_EX

    # Money + PnL
    POSITIVE = Fore.GREEN
    NEGATIVE = Fore.RED
    NEUTRAL = Fore.WHITE

    # Strategy badges
    STRATEGY_CROSS_MOMENTUM = Fore.CYAN
    STRATEGY_STAT_ARB = Fore.MAGENTA
    STRATEGY_TRIANGULAR_ARB = Fore.YELLOW
    STRATEGY_DEFENSIVE = Fore.LIGHTRED_EX

    # Watchdog
    WATCHDOG_HEALTHY = Fore.GREEN
    WATCHDOG_DEGRADED = Fore.YELLOW
    WATCHDOG_FAILED = Fore.RED

    # Reset
    RESET = Style.RESET_ALL


# ---------------------------------------------------------------------------
# Per-asset terminal palette
# ---------------------------------------------------------------------------
# Kept distinct from the semantic tokens above so swapping the semantic palette
# doesn't disturb asset coloring.

ASSET_PALETTE: dict[str, str] = {
    "BTC": Fore.YELLOW,
    "ETH": Fore.CYAN,
    "SOL": Fore.MAGENTA,
    "ADA": Fore.BLUE,
    "XRP": Fore.WHITE,
    "DOT": Fore.LIGHTMAGENTA_EX,
    "LINK": Fore.LIGHTBLUE_EX,
    "AVAX": Fore.RED,
    "ATOM": Fore.LIGHTCYAN_EX,
    "LTC": Fore.LIGHTWHITE_EX,
    "DOGE": Fore.YELLOW,
    "BNB": Fore.LIGHTYELLOW_EX,
    "UNI": Fore.LIGHTRED_EX,
    "AAVE": Fore.GREEN,
    "ARB": Fore.CYAN,
    "OP": Fore.RED,
    "POL": Fore.MAGENTA,
    "USD": Fore.GREEN,
}
ASSET_FALLBACK = Fore.WHITE


def asset_color(asset: str) -> str:
    """ANSI color for a given asset code (case-insensitive)."""
    return ASSET_PALETTE.get(asset.upper(), ASSET_FALLBACK)


def colorize(text: str, token: str) -> str:
    """Wrap text in an ANSI escape and an auto-reset."""
    return f"{token}{text}{TerminalToken.RESET}"


def pnl_color(value: float) -> str:
    """Green for >= 0, red otherwise."""
    return TerminalToken.POSITIVE if value >= 0 else TerminalToken.NEGATIVE


# ---------------------------------------------------------------------------
# Discord embed colors
# ---------------------------------------------------------------------------
# Discord rich-embed `color` field expects a 24-bit integer (`0xRRGGBB`).
# Keep these aligned with the semantic terminal tokens above.

@dataclass(frozen=True)
class DiscordEmbedColor:
    """RGB integers ready to drop into a Discord embed `color` field."""

    SUCCESS: int = 0x2ECC71          # green
    ERROR: int = 0xE74C3C            # red
    WARNING: int = 0xF1C40F          # amber
    INFO: int = 0x3498DB             # blue
    MUTED: int = 0x95A5A6            # gray

    BUY: int = 0x27AE60              # darker green
    SELL: int = 0xC0392B             # darker red

    TRADE_EXECUTED: int = 0x9B59B6   # purple — important + neutral
    HEARTBEAT: int = 0x5865F2        # Discord blurple
    HIBERNATING: int = 0xD35400      # burnt orange — drawdown
    CIRCUIT_BREAKER: int = 0x8E44AD  # purple — manual intervention required
    ADAPTIVE_MODE: int = 0x1ABC9C    # teal — relaxed
    STRATEGY_SWITCH: int = 0x16A085  # teal-dark
    MILESTONE: int = 0xFFD700        # gold


DISCORD = DiscordEmbedColor()


__all__ = [
    "ASSET_FALLBACK",
    "ASSET_PALETTE",
    "DISCORD",
    "DiscordEmbedColor",
    "TerminalToken",
    "asset_color",
    "colorize",
    "pnl_color",
]
