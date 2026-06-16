"""Resume from live route halt without clearing drawdown halt."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from bot.engine import TradingEngine


def _minimal_engine(tmp_path: Path) -> TradingEngine:
    engine = TradingEngine.__new__(TradingEngine)
    engine._mirror_mode = True
    engine.settings = MagicMock()
    engine.circuit_breaker = MagicMock(in_reevaluation=lambda: False)
    engine.live_circuit_breaker = None
    engine.risk = MagicMock()
    engine.risk.state = MagicMock(paused_until=None, hibernate_alert_sent=False)
    engine.broker = MagicMock(save=MagicMock())
    engine.live_broker = MagicMock(
        halted=True,
        halt_reason="Live leg 2/3 failed on UNI/BTC: EOrder:Insufficient funds",
        save=MagicMock(),
    )
    return engine


def test_resume_live_clears_route_halt(tmp_path: Path) -> None:
    engine = _minimal_engine(tmp_path)
    reply = TradingEngine._handle_discord_command(engine, "resume-live", "")
    assert engine.live_broker.halted is False
    assert "route halt **cleared**" in reply.lower()


def test_resume_live_keeps_drawdown_halt(tmp_path: Path) -> None:
    engine = _minimal_engine(tmp_path)
    engine.live_broker.halt_reason = "Live drawdown halt — 10.2% exceeded"
    reply = TradingEngine._handle_discord_command(engine, "resume-live", "")
    assert engine.live_broker.halted is True
    assert "drawdown" in reply.lower()
