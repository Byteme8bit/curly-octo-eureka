"""Tests for bot.paper_portfolio."""

from __future__ import annotations

from pathlib import Path

from bot.paper_portfolio import PaperPortfolioLog


def test_write_and_load_roundtrip(tmp_path: Path):
    path = tmp_path / "paper_portfolio.json"
    log = PaperPortfolioLog(path)
    log.write(
        holdings={"ETH": 0.41, "AAVE": 6.9, "USD": 0.0},
        usd_prices={"ETH": 2091.0, "AAVE": 85.7},
        portfolio_usd=2126.45,
        baseline_pnl=-0.30,
        drawdown_pct=0.0012,
        updated_at="2026-05-25 22:01:22 PDT",
    )
    snap = log.load()
    assert snap is not None
    assert snap.portfolio_usd == 2126.45
    assert snap.baseline_pnl == -0.30
    assert set(snap.balances()) == {"ETH", "AAVE"}
    assert snap.holdings["ETH"]["usd_value"] > 800


def test_format_text_lists_holdings(tmp_path: Path):
    path = tmp_path / "paper_portfolio.json"
    log = PaperPortfolioLog(path)
    log.write(
        holdings={"ADA": 83.0},
        usd_prices={"ADA": 0.24},
        portfolio_usd=19.99,
        baseline_pnl=0.0,
        drawdown_pct=0.0,
    )
    text = log.format_text()
    assert "Paper portfolio" in text
    assert "ADA" in text
    assert "$19.99" in text


def test_clear_removes_file(tmp_path: Path):
    path = tmp_path / "paper_portfolio.json"
    log = PaperPortfolioLog(path)
    log.write(
        holdings={"ETH": 1.0},
        usd_prices={"ETH": 2000.0},
        portfolio_usd=2000.0,
        baseline_pnl=0.0,
        drawdown_pct=0.0,
    )
    assert path.exists()
    log.clear()
    assert not path.exists()
    assert log.load() is None


def test_bootstrap_from_paper_state(tmp_path: Path):
    state = tmp_path / ".paper_state.json"
    state.write_text(
        '{"balances": {"ETH": 0.41, "AAVE": 6.9, "USD": 0}, '
        '"risk": {"baseline_portfolio": 2000, "peak_portfolio": 2100}}',
        encoding="utf-8",
    )
    path = tmp_path / "paper_portfolio.json"
    log = PaperPortfolioLog(path)
    snap = log.bootstrap_from_state(state)
    assert snap is not None
    assert path.exists()
    assert set(snap.balances()) == {"ETH", "AAVE"}
    text = log.format_text()
    assert "AAVE" in text
    assert "$2,126" not in text or "pending" in text.lower() or "0.4100" in text


def test_format_text_falls_back_to_state(tmp_path: Path):
    state = tmp_path / ".paper_state.json"
    state.write_text(
        '{"balances": {"ADA": 83.0}, "risk": {}}',
        encoding="utf-8",
    )
    path = tmp_path / "paper_portfolio.json"
    log = PaperPortfolioLog(path)
    text = log.format_text(state_file=state)
    assert "ADA" in text
    assert "Bootstrapped" in text or "paper state" in text.lower()
