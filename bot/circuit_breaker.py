"""Global 15% drawdown circuit breaker and re-evaluation mode."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from bot.local_time import format_pacific
from bot.strategies.base import TradeIntent

logger = logging.getLogger(__name__)


@dataclass
class CircuitBreakerEvent:
    portfolio_value: float
    peak_portfolio: float
    drawdown_pct: float
    triggered_at: datetime


class CircuitBreaker:
    """
    Peak-to-trough 15% loss triggers Global Emergency Pause.
    Requires manual reset (Discord `reset` / `resume-trading`) to exit re-evaluation mode.
    """

    def __init__(
        self,
        risk_state,
        drawdown_limit_pct: float,
        save_callback,
        diagnostic_dir: Path,
    ):
        self.state = risk_state
        self.drawdown_limit_pct = drawdown_limit_pct
        self._save = save_callback
        self.diagnostic_dir = diagnostic_dir

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def check(self, portfolio_value: float) -> CircuitBreakerEvent | None:
        peak = self.state.peak_portfolio
        if peak <= 0 or self.in_reevaluation():
            return None
        drawdown = (peak - portfolio_value) / peak
        if drawdown < self.drawdown_limit_pct:
            return None

        self.state.reevaluation_mode = True
        self.state.circuit_breaker_at = self._now().isoformat()
        self.state.paused_until = None
        self.state.hibernate_alert_sent = False
        self._save()

        return CircuitBreakerEvent(
            portfolio_value=portfolio_value,
            peak_portfolio=peak,
            drawdown_pct=drawdown,
            triggered_at=self._now(),
        )

    def in_reevaluation(self) -> bool:
        return bool(getattr(self.state, "reevaluation_mode", False))

    def status_message(self) -> str:
        if not self.in_reevaluation():
            return ""
        at = getattr(self.state, "circuit_breaker_at", None)
        when = format_pacific(datetime.fromisoformat(at)) if at else "unknown"
        return (
            f"RE-EVALUATION MODE — {self.drawdown_limit_pct:.0%} circuit breaker tripped at {when}. "
            "Send `resume-trading` after review or `reset` to clear."
        )

    def clear_reevaluation(self) -> None:
        self.state.reevaluation_mode = False
        self.state.circuit_breaker_at = None
        self._save()

    def defensive_intents(
        self,
        holdings: dict[str, float],
        usd_prices: dict[str, float],
        safe_assets: tuple[str, ...],
        dust_usd: float,
    ) -> list[TradeIntent]:
        """Swap volatile holdings into configured safe assets / USD."""
        intents: list[TradeIntent] = []
        safe = set(safe_assets) | {"USD"}
        for asset, qty in holdings.items():
            if asset in safe or qty <= 0:
                continue
            value = qty * usd_prices.get(asset, 0.0)
            if value < dust_usd:
                continue
            target = "USD" if "USD" in safe else safe_assets[0]
            intents.append(
                TradeIntent(
                    from_asset=asset,
                    to_asset=target,
                    reason=(
                        f"circuit breaker — de-risking {asset} into {target} "
                        f"({self.drawdown_limit_pct:.0%} portfolio drawdown limit)"
                    ),
                    size_pct=1.0,
                    edge=0.0,
                    gross_return_pct=0.0,
                    is_defensive=True,
                    strategy_name="circuit_breaker",
                )
            )
        return intents

    def dump_diagnostics(
        self,
        event: CircuitBreakerEvent,
        holdings: dict[str, float],
        usd_prices: dict[str, float],
        extra: dict | None = None,
    ) -> Path:
        self.diagnostic_dir.mkdir(parents=True, exist_ok=True)
        stamp = format_pacific(event.triggered_at, "%Y%m%d-%H%M%S")
        path = self.diagnostic_dir / f"circuit_breaker_{stamp}.json"
        payload = {
            "triggered_at": event.triggered_at.isoformat(),
            "portfolio_value": event.portfolio_value,
            "peak_portfolio": event.peak_portfolio,
            "drawdown_pct": event.drawdown_pct,
            "holdings": holdings,
            "usd_prices": usd_prices,
            "extra": extra or {},
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        logger.warning("Circuit breaker diagnostic written to %s", path)
        return path
