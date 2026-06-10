"""Log and state parsers for the local dashboard."""

from dashboard.parsers.auditor import build_auditor_view
from dashboard.parsers.series import build_forecasts, build_portfolio_history, build_trades_series
from dashboard.parsers.timeline import build_timeline
from dashboard.parsers.tradebot import build_tradebot_view
from dashboard.parsers.watchdog import build_watchdog_view
from dashboard.parsers.whales import build_whale_view

__all__ = [
    "build_auditor_view",
    "build_forecasts",
    "build_portfolio_history",
    "build_timeline",
    "build_tradebot_view",
    "build_trades_series",
    "build_watchdog_view",
    "build_whale_view",
]
