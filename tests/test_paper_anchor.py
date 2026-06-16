"""Paper-to-live anchoring in mirror mode."""

from __future__ import annotations

from pathlib import Path

import pytest

from bot.live_broker import LiveBroker
from bot.paper_anchor import anchor_paper_broker_to_live, live_balances_snapshot
from bot.paper_broker import PaperBroker


class _StubExchange:
    def __init__(self) -> None:
        self.balances = {"ETH": 0.87, "USD": 149.0, "UNI": 12.0}

    def fetch_balance(self):
        return {"total": dict(self.balances)}


def _live_broker(tmp_path: Path) -> LiveBroker:
    return LiveBroker(
        exchange=_StubExchange(),
        fee_rate=0.0026,
        state_file=tmp_path / ".live_state.json",
        allowed_assets=("ETH", "ADA", "UNI"),
        sync_assets=frozenset({"ETH", "USD", "UNI", "ADA", "BTC"}),
    )


def _paper_broker(tmp_path: Path) -> PaperBroker:
    broker = PaperBroker(
        initial_balances={"ETH": 1.0, "USD": 0.0},
        fee_rate=0.0026,
        state_file=tmp_path / ".paper_state.json",
    )
    broker.state.balances = {"ETH": 2.5, "USD": 500.0, "DOT": 100.0}
    broker.state.trades = [{"time": "t1", "symbol": "ETH/USD"}]
    broker.state.risk.baseline_portfolio = 12000.0
    broker.state.risk.peak_portfolio = 12500.0
    broker.save()
    return broker


def test_live_balances_snapshot(tmp_path: Path) -> None:
    live = _live_broker(tmp_path)
    snap = live_balances_snapshot(live)
    assert snap["ETH"] == pytest.approx(0.87)
    assert snap["USD"] == pytest.approx(149.0)
    assert "DOT" not in snap


def test_anchor_replaces_paper_balances_and_resets_risk(tmp_path: Path) -> None:
    live = _live_broker(tmp_path)
    paper = _paper_broker(tmp_path)
    prices = {"USD": 1.0, "ETH": 3500.0, "UNI": 8.0}

    anchored = anchor_paper_broker_to_live(paper, live, prices, preserve_trades=True)

    assert paper.balance("DOT") == 0.0
    assert paper.balance("ETH") == pytest.approx(0.87)
    assert paper.balance("USD") == pytest.approx(149.0)
    assert paper.balance("UNI") == pytest.approx(12.0)
    assert len(paper.state.trades) == 1
    assert paper.state.risk.baseline_portfolio == pytest.approx(anchored)
    assert paper.state.risk.peak_portfolio == pytest.approx(anchored)
    assert anchored == pytest.approx(149.0 + 0.87 * 3500.0 + 12.0 * 8.0)


def test_anchor_clear_trades_on_reset(tmp_path: Path) -> None:
    live = _live_broker(tmp_path)
    paper = _paper_broker(tmp_path)
    prices = {"USD": 1.0, "ETH": 3500.0, "UNI": 8.0}

    anchor_paper_broker_to_live(paper, live, prices, preserve_trades=False)

    assert paper.state.trades == []


def test_paper_anchor_defaults_on_in_mirror_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVE_MIRROR_PAPER", "1")
    monkeypatch.delenv("PAPER_ANCHOR_TO_LIVE", raising=False)
    from config import load_settings

    assert load_settings().paper_anchor_to_live is True


def test_paper_anchor_respects_explicit_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVE_MIRROR_PAPER", "1")
    monkeypatch.setenv("PAPER_ANCHOR_TO_LIVE", "0")
    from config import load_settings

    assert load_settings().paper_anchor_to_live is False

