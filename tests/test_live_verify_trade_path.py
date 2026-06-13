"""Live verify tag must never block trade execution or Discord alerts."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from bot.engine import TradingEngine


def _sample_trade() -> dict:
    return {
        "from_asset": "USD",
        "to_asset": "ETH",
        "symbol": "ETH/USD",
        "gain_loss": 1.25,
        "reason": "test trade",
        "size_pct": 0.1,
        "fee_usd": 0.5,
        "price": 3000.0,
        "edge": 0.01,
    }


def test_live_verify_tag_exception_returns_empty() -> None:
    engine = TradingEngine.__new__(TradingEngine)
    engine.settings = MagicMock(trade_verify_discord_tag=True, trade_verify_skip_kraken=True)
    with patch(
        "bot.engine.build_live_verify_tag",
        side_effect=RuntimeError("Kraken ticker unavailable"),
    ):
        tag = engine._live_verify_tag(_sample_trade(), {"ETH": 3000.0})
    assert tag == ""


def test_notify_discord_trades_posts_when_live_tag_fails() -> None:
    engine = TradingEngine.__new__(TradingEngine)
    engine.settings = MagicMock(discord_enabled=True, discord_pin_trade_usd=500.0)
    engine.discord = MagicMock()
    with patch.object(TradingEngine, "_live_verify_tag", return_value=""):
        engine._notify_discord_trades(
            [_sample_trade()],
            portfolio=3500.0,
            baseline_pnl=1400.0,
            usd_prices={"ETH": 3000.0},
        )
    engine.discord.post_important.assert_called_once()
    msg = engine.discord.post_important.call_args[0][0]
    assert "Trade executed" in msg
