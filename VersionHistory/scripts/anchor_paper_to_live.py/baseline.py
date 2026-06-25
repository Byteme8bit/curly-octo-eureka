"""One-shot: anchor .paper_state.json balances to current Kraken spot."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.data import KrakenData
from bot.live_broker import LiveBroker
from bot.paper_anchor import anchor_paper_broker_to_live
from bot.paper_broker import PaperBroker
from config import load_settings


def main() -> int:
    settings = load_settings()
    if not settings.live_mirror_paper or not settings.live_enabled:
        print("FAIL: LIVE_MIRROR_PAPER=1 and LIVE_ENABLED=1 required")
        return 1
    if not settings.paper_anchor_to_live:
        print("FAIL: PAPER_ANCHOR_TO_LIVE=1 required (or default on in mirror mode)")
        return 1
    if not settings.api_key or not settings.api_secret:
        print("FAIL: Kraken API keys missing in .env")
        return 1

    data = KrakenData(settings)
    live_broker = LiveBroker(
        exchange=data.exchange,
        fee_rate=settings.fee_rate,
        state_file=settings.live_state_file,
        min_usd_trade=settings.min_usd_trade,
        max_usd_per_trade=settings.live_max_usd_per_trade,
        max_usd_per_route=settings.live_max_usd_per_route,
        allowed_assets=settings.live_allowed_assets,
        allow_triangular=settings.live_allow_triangular,
        max_route_legs=settings.live_max_route_legs,
        reset=False,
        equity_assets=settings.equity_assets,
    )
    live_broker.sync_from_exchange()

    paper_broker = PaperBroker(
        initial_balances=settings.initial_balances,
        fee_rate=settings.fee_rate,
        state_file=settings.state_file,
        min_usd_trade=settings.min_usd_trade,
        reset=False,
    )

    assets = list({*live_broker.state.balances, *paper_broker.state.balances})
    usd_prices = data.fetch_usd_prices(assets)
    live_usd = live_broker.portfolio_value(usd_prices)
    paper_usd = paper_broker.portfolio_value(usd_prices)

    anchored = anchor_paper_broker_to_live(
        paper_broker,
        live_broker,
        usd_prices,
        preserve_trades=True,
    )

    print("OK — paper anchored to live Kraken spot")
    print(f"live_portfolio_usd:  {live_usd:.2f}")
    print(f"paper_before_usd:    {paper_usd:.2f}")
    print(f"paper_after_usd:     {anchored:.2f}")
    for asset in sorted(live_broker.state.balances):
        qty = live_broker.balance(asset)
        if qty > 0:
            px = usd_prices.get(asset, 1.0 if asset == "USD" else 0.0)
            print(f"  {asset}: {qty:.6f}  (~${qty * px:.2f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
