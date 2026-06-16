"""Tests for scan-activity Discord line."""

from bot.discord_summary import format_tick_activity_line


def test_tick_activity_line_includes_scan_and_blocks() -> None:
    line = format_tick_activity_line(
        last_scan_at="2026-06-15 22:00:00 PDT",
        opportunity_count=42,
        top_block_reason="ETH reserve — cannot sell below 0.50 ETH",
        poll_interval=15,
        idle_hours=0.5,
        paper_trades_session=300,
        live_trades_session=16,
    )
    assert "Last scan" in line
    assert "42 routes" in line
    assert "paper 300" in line
    assert "live 16" in line
    assert "top block" in line
    assert "ETH reserve" in line


def test_tick_activity_line_live_halted() -> None:
    line = format_tick_activity_line(
        last_scan_at="now",
        opportunity_count=0,
        live_halted=True,
        live_halt_reason="drawdown exceeded 10%",
    )
    assert "LIVE HALTED" in line
    assert "drawdown" in line
