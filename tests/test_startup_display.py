"""Tests for terminal startup portfolio display."""

from __future__ import annotations

from bot.display import TerminalDisplay


def test_startup_portfolio_shows_loaded_nonzero_balances(capsys):
    display = TerminalDisplay(log_writer=lambda _: None)
    display.startup(
        strategy="orchestrator",
        timeframe="5m",
        interval=15,
        balances={
            "ETH": 0.4106,
            "ADA": 83.0,
            "AAVE": 6.9157,
            "ATOM": 305.3465,
            "USD": 0.0,
        },
    )
    out = capsys.readouterr().out
    assert "0.4106" in out or "0.410" in out
    assert "AAVE" in out
    assert "ATOM" in out
    assert "'USD'" not in out  # zero balances omitted


def test_startup_portfolio_not_config_defaults(capsys):
    """Regression: banner must not hardcode INITIAL_BALANCES when state differs."""
    display = TerminalDisplay(log_writer=lambda _: None)
    display.startup(
        strategy="test",
        timeframe="5m",
        interval=15,
        balances={"ETH": 0.41, "AAVE": 6.9},
    )
    out = capsys.readouterr().out
    assert "1.0" not in out or "0.41" in out
    assert "AAVE" in out
    assert "83" not in out
