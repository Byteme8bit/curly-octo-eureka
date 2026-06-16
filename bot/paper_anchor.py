"""Anchor paper broker balances to live Kraken spot (mirror mode)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot.live_broker import LiveBroker
    from bot.paper_broker import PaperBroker

logger = logging.getLogger(__name__)


def live_balances_snapshot(live_broker: LiveBroker) -> dict[str, float]:
    """Positive balances from the live broker state."""
    return {
        str(asset): float(qty)
        for asset, qty in live_broker.state.balances.items()
        if float(qty) > 0
    }


def anchor_paper_broker_to_live(
    paper_broker: PaperBroker,
    live_broker: LiveBroker,
    usd_prices: dict[str, float],
    *,
    preserve_trades: bool = True,
) -> float:
    """Replace paper balances with the live Kraken snapshot; return portfolio USD."""
    live_balances = live_balances_snapshot(live_broker)
    trades = list(paper_broker.state.trades) if preserve_trades else []

    paper_broker.state.balances = dict(live_balances)
    paper_broker.state.cost_basis = {}
    paper_broker.ensure_cost_basis(usd_prices)

    portfolio = paper_broker.portfolio_value(usd_prices)
    now = datetime.now(timezone.utc).isoformat()

    risk = paper_broker.state.risk
    risk.baseline_portfolio = portfolio
    risk.peak_portfolio = portfolio
    risk.session_started_at = now
    risk.growth_window_start_at = now
    risk.growth_window_start_value = portfolio
    risk.reevaluation_mode = False
    risk.circuit_breaker_at = None
    risk.paused_until = None
    risk.hibernate_alert_sent = False
    risk.adaptive_suspended = False
    risk.adaptive_suspended_at = None
    risk.adaptive_relax_attempts = 0
    risk.adaptive_alert_sent = False

    paper_broker.state.trades = trades
    paper_broker.save()

    logger.info(
        "Paper anchored to live Kraken spot: $%.2f (%d assets, preserve_trades=%s)",
        portfolio,
        len(live_balances),
        preserve_trades,
    )
    return portfolio
