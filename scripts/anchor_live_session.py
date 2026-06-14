"""Anchor live session day-zero baseline from Kraken balances."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.data import KrakenData
from bot.live_broker import LiveBroker
from bot.local_time import format_pacific
from bot.paper_portfolio import PaperPortfolioLog
from bot.verifier.summary import codebase_has_live_broker
from config import load_settings

# Non-tradable / ignore for portfolio display
_SKIP_DISPLAY = frozenset({"KFEE", "BABY", "BCH"})


def _portfolio_usd(balances: dict[str, float], usd_prices: dict[str, float]) -> float:
    total = 0.0
    for asset, qty in balances.items():
        if qty <= 0 or asset in _SKIP_DISPLAY:
            continue
        if asset == "USD":
            total += qty
        else:
            total += qty * usd_prices.get(asset, 0.0)
    return total


def main() -> int:
    settings = load_settings()
    if not settings.api_key or not settings.api_secret:
        print("FAIL: Kraken API keys missing in .env")
        return 1

    data = KrakenData(settings)
    broker = LiveBroker(
        exchange=data.exchange,
        fee_rate=settings.fee_rate,
        state_file=settings.live_state_file,
        min_usd_trade=settings.min_usd_trade,
        max_usd_per_trade=settings.live_max_usd_per_trade,
        reset=False,
    )
    broker.sync_from_exchange()
    broker.halted = False
    broker.halt_reason = ""

    assets = [a for a, q in broker.state.balances.items() if q > 0 and a not in _SKIP_DISPLAY]
    usd_prices = data.fetch_usd_prices(assets)
    portfolio = _portfolio_usd(broker.state.balances, usd_prices)

    now_utc = datetime.now(timezone.utc).isoformat()
    risk = broker.risk
    risk.baseline_portfolio = portfolio
    risk.peak_portfolio = portfolio
    risk.session_started_at = now_utc
    risk.reevaluation_mode = False
    risk.circuit_breaker_at = None
    risk.paused_until = None
    risk.hibernate_alert_sent = False
    risk.adaptive_suspended = False
    risk.adaptive_suspended_at = None
    risk.adaptive_relax_attempts = 0
    risk.adaptive_alert_sent = False
    risk.last_trade_at = broker.state.trades[-1]["time"] if broker.state.trades else None

    broker.ensure_cost_basis(usd_prices)
    broker.save()

    display_holdings = {
        a: broker.balance(a)
        for a in sorted(broker.state.balances)
        if broker.balance(a) > 0 and a not in _SKIP_DISPLAY
    }
    PaperPortfolioLog(settings.paper_portfolio_file).write(
        holdings=display_holdings,
        usd_prices=usd_prices,
        portfolio_usd=portfolio,
        baseline_pnl=0.0,
        drawdown_pct=0.0,
    )

    session_doc = {
        "anchored_at_utc": now_utc,
        "anchored_at_pacific": format_pacific(),
        "baseline_portfolio_usd": round(portfolio, 2),
        "peak_portfolio_usd": round(portfolio, 2),
        "halt_drawdown_pct": settings.live_drawdown_halt_pct,
        "halt_portfolio_usd": round(portfolio * (1 - settings.live_drawdown_halt_pct), 2),
        "test_trade_order_id": "OX7B5B-LROFK-CFJ6BU",
        "balances": {k: round(v, 8) for k, v in display_holdings.items()},
        "usd_prices": {k: round(v, 6) for k, v in usd_prices.items() if k in display_holdings},
        "live_broker_importable": codebase_has_live_broker(),
    }
    start_file = ROOT / "live_session_start.json"
    start_file.write_text(json.dumps(session_doc, indent=2), encoding="utf-8")

    print("OK — live session anchored")
    print(f"portfolio_usd: {portfolio:.2f}")
    print(f"halt_at_10pct: {portfolio * (1 - settings.live_drawdown_halt_pct):.2f}")
    for asset in ("ETH", "USD", "ADA"):
        qty = broker.balance(asset)
        px = usd_prices.get(asset, 1.0 if asset == "USD" else 0.0)
        print(f"  {asset}: {qty:.6f}  (~${qty * px:.2f})")
    print(f"live_broker: {codebase_has_live_broker()}")
    print(f"session_file: {start_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
