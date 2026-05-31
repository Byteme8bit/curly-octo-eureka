"""Tests for bot.paper_broker — focusing on trade retention cap."""
from __future__ import annotations

import json
from pathlib import Path

from bot.paper_broker import MAX_TRADES_RETAINED, PaperBroker, PaperState


def _make_broker(tmp_path: Path, *, initial_usd: float = 10_000.0) -> PaperBroker:
    return PaperBroker(
        initial_balances={"USD": initial_usd, "ETH": 0.0},
        fee_rate=0.0026,
        state_file=tmp_path / ".paper_state.json",
    )


def _seed_trades(broker: PaperBroker, n: int) -> None:
    """Directly append fake trade records without going through execute()."""
    for i in range(n):
        broker.state.trades.append({"seq": i, "stub": True})


def test_save_prunes_trades_above_cap(tmp_path: Path):
    broker = _make_broker(tmp_path)
    _seed_trades(broker, MAX_TRADES_RETAINED + 50)
    broker.save()
    assert len(broker.state.trades) == MAX_TRADES_RETAINED
    # On-disk file must also reflect the pruned count
    data = json.loads((tmp_path / ".paper_state.json").read_text(encoding="utf-8"))
    assert len(data["trades"]) == MAX_TRADES_RETAINED


def test_save_keeps_trades_at_or_below_cap(tmp_path: Path):
    broker = _make_broker(tmp_path)
    _seed_trades(broker, MAX_TRADES_RETAINED)
    broker.save()
    assert len(broker.state.trades) == MAX_TRADES_RETAINED


def test_load_prunes_oversized_trades_on_disk(tmp_path: Path):
    """A .paper_state.json written by an older bot (no cap) is pruned on first load."""
    state_file = tmp_path / ".paper_state.json"
    payload = {
        "balances": {"USD": 9000.0, "ETH": 0.0},
        "cost_basis": {},
        "trades": [{"seq": i} for i in range(MAX_TRADES_RETAINED + 100)],
        "risk": {},
    }
    state_file.write_text(json.dumps(payload), encoding="utf-8")
    broker = PaperBroker(
        initial_balances={"USD": 9000.0, "ETH": 0.0},
        fee_rate=0.0026,
        state_file=state_file,
    )
    assert len(broker.state.trades) == MAX_TRADES_RETAINED


def test_save_retains_most_recent_trades(tmp_path: Path):
    """When pruning, the OLDEST trades are dropped (most-recent 500 are kept)."""
    broker = _make_broker(tmp_path)
    _seed_trades(broker, MAX_TRADES_RETAINED + 10)
    broker.save()
    seqs = [t["seq"] for t in broker.state.trades]
    # First entry should be seq=10 (0-9 were dropped)
    assert seqs[0] == 10
    assert seqs[-1] == MAX_TRADES_RETAINED + 9
