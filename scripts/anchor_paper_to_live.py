"""One-shot: anchor .paper_state.json balances to current Kraken spot."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.data import KrakenData
from bot.live_broker import LiveBroker
from bot.paper_anchor import (
    anchor_paper_broker_to_live,
    save_paper_baseline,
)
from bot.paper_broker import PaperBroker
from config import load_settings


def _build_live_broker(settings, data: KrakenData) -> LiveBroker:
    return LiveBroker(
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--paper-only",
        action="store_true",
        help="Anchor from Kraken API without LIVE_ENABLED or mirror mode",
    )
    parser.add_argument(
        "--clear-trades",
        action="store_true",
        help="Drop paper trade history after anchor (like RESET_PAPER_STATE=1)",
    )
    parser.add_argument(
        "--no-baseline",
        action="store_true",
        help="Skip writing paper_baseline.json",
    )
    args = parser.parse_args(argv)

    settings = load_settings()
    if not settings.api_key or not settings.api_secret:
        print("FAIL: Kraken API keys missing in .env")
        return 1

    mirror_mode = settings.live_mirror_paper and settings.live_enabled
    if not args.paper_only:
        if not mirror_mode:
            print("FAIL: LIVE_MIRROR_PAPER=1 and LIVE_ENABLED=1 required (or use --paper-only)")
            return 1
        if not settings.paper_anchor_to_live:
            print("FAIL: PAPER_ANCHOR_TO_LIVE=1 required (or default on in mirror mode)")
            return 1
    elif not settings.paper_anchor_to_live:
        print("WARN: PAPER_ANCHOR_TO_LIVE=0 — proceeding because --paper-only was passed")

    data = KrakenData(settings)
    live_broker = _build_live_broker(settings, data)
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

    preserve_trades = not args.clear_trades
    anchored = anchor_paper_broker_to_live(
        paper_broker,
        live_broker,
        usd_prices,
        preserve_trades=preserve_trades,
    )

    if not args.no_baseline:
        save_paper_baseline(
            settings.paper_reset_baseline_path,
            balances=live_broker.state.balances,
            usd_prices=usd_prices,
            portfolio_usd=anchored,
        )

    mode = "paper-only" if args.paper_only else "mirror"
    print(f"OK — paper anchored to live Kraken spot ({mode})")
    print(f"live_portfolio_usd:  {live_usd:.2f}")
    print(f"paper_before_usd:    {paper_usd:.2f}")
    print(f"paper_after_usd:     {anchored:.2f}")
    print(f"baseline_file:       {settings.paper_reset_baseline_path}")
    for asset in sorted(live_broker.state.balances):
        qty = live_broker.balance(asset)
        if qty > 0:
            px = usd_prices.get(asset, 1.0 if asset in ("USD", "USDC") else 0.0)
            print(f"  {asset}: {qty:.6f}  (~${qty * px:.2f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
