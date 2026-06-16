"""Discord ``TradeBot -portfolio`` formatting — live vs paper labels."""

from bot.report import format_portfolio_command, format_portfolio_summary

_PRICES = {"USD": 1.0, "ETH": 3500.0, "UNI": 8.0}


def test_paper_only_unchanged() -> None:
    text = format_portfolio_command(
        portfolio=495.0,
        baseline_pnl=12.5,
        drawdown=0.01,
        holdings={"USD": 100.0, "ETH": 0.1},
        usd_prices=_PRICES,
        trading_active=True,
        live_enabled=False,
    )
    expected = format_portfolio_summary(
        portfolio=495.0,
        baseline_pnl=12.5,
        drawdown=0.01,
        holdings={"USD": 100.0, "ETH": 0.1},
        usd_prices=_PRICES,
        trading_active=True,
    )
    assert text == expected
    assert "Live Kraken" not in text


def test_mirror_mode_shows_live_then_paper() -> None:
    text = format_portfolio_command(
        portfolio=495.0,
        baseline_pnl=12.5,
        drawdown=0.01,
        holdings={"USD": 50.0, "ETH": 0.12},
        usd_prices=_PRICES,
        trading_active=True,
        live_enabled=True,
        mirror_mode=True,
        paper_anchor_to_live=True,
        live_portfolio=1644.0,
        live_session_pnl=-10.0,
        live_drawdown=0.025,
        live_holdings={"USD": 149.0, "ETH": 0.87, "UNI": 12.0},
    )
    assert text.index("Live Kraken spot") < text.index("[Paper sim]")
    assert "Session PnL -10.00" in text
    assert "Portfolio  $1,644.00" in text
    assert "anchored to live at session start" in text
    assert "PAPER_ANCHOR_TO_LIVE=1" in text
    assert "Portfolio  $495.00" in text
    assert "ETH" in text
    assert "UNI" in text


def test_mirror_mode_without_anchor_keeps_legacy_label() -> None:
    text = format_portfolio_command(
        portfolio=12000.0,
        baseline_pnl=500.0,
        drawdown=0.02,
        holdings={"USD": 50.0, "ETH": 3.0},
        usd_prices=_PRICES,
        trading_active=True,
        live_enabled=True,
        mirror_mode=True,
        paper_anchor_to_live=False,
        live_portfolio=1644.0,
        live_session_pnl=-10.0,
        live_drawdown=0.025,
        live_holdings={"USD": 149.0, "ETH": 0.87},
    )
    assert "[Paper sim] — not Kraken balance" in text
    assert "anchored to live" not in text


def test_pure_live_labels_kraken_not_paper() -> None:
    text = format_portfolio_command(
        portfolio=1644.0,
        baseline_pnl=-10.0,
        drawdown=0.025,
        holdings={"USD": 149.0, "ETH": 0.87},
        usd_prices=_PRICES,
        trading_active=True,
        live_enabled=True,
        mirror_mode=False,
    )
    assert "Live Kraken spot" in text
    assert "[Paper sim]" not in text
    assert "Session PnL -10.00" in text
