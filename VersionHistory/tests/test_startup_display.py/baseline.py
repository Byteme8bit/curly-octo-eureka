"""Tests for terminal startup portfolio display."""

from __future__ import annotations

from bot.display import TerminalDisplay
from bot.status import StatusSnapshot


def test_startup_portfolio_shows_loaded_nonzero_balances(capsys):
    display = TerminalDisplay()
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
    display = TerminalDisplay()
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


def test_tick_survives_broken_stdout(monkeypatch):
    """Background/redirected stdout must not break the trading loop."""
    import bot.display as display_module

    display_module._stdout_ok = True

    def bad_print(*args, **kwargs):
        raise OSError(22, "Invalid argument")

    monkeypatch.setattr("builtins.print", bad_print)
    display = TerminalDisplay()
    status = StatusSnapshot(
        mode="hold",
        summary_key="hold:test",
        idle_reason="idle",
        considering=["ETH -> USD"],
    )
    display.tick(
        portfolio=1000.0,
        usd_prices={"ETH": 2000.0},
        holdings={"ETH": 1.0},
        trades=[],
        status=status,
        status_changed=True,
        status_since=None,
    )
    assert display._last_status_key == "hold:test"
    display.tick(
        portfolio=1000.0,
        usd_prices={"ETH": 2000.0},
        holdings={"ETH": 1.0},
        trades=[],
        status=status,
        status_changed=False,
        status_since="2026-06-02 10:00:00 PDT",
    )
