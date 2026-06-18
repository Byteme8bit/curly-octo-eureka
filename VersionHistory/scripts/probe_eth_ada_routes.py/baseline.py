"""One-shot probe: live Kraken balances + ETH/ADA single-hop route net edges."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.data import KrakenData
from bot.fee_engine import FeeEngine
from bot.live_broker import LiveBroker
from bot.markets import MarketRegistry
from bot.preflight import PreFlightValidator
from bot.strategies.base import TradeIntent
from bot.strategies.registry import build_orchestrator
from config import load_settings


def main() -> int:
    settings = load_settings()
    data = KrakenData(settings)
    fee_engine = FeeEngine(data.exchange, settings)
    preflight = PreFlightValidator(
        fee_engine, settings.slippage_buffer_pct, settings.min_net_profit_pct
    )
    markets = MarketRegistry(
        data.exchange,
        settings.watch_assets,
        equity_assets=settings.equity_assets,
    )
    live = LiveBroker(
        exchange=data.exchange,
        fee_rate=settings.fee_rate,
        state_file=ROOT / ".live_state.json",
        min_usd_trade=settings.min_usd_trade,
        max_usd_per_trade=settings.live_max_usd_per_trade,
        reset=False,
    )
    live.sync_from_exchange()

    usd_prices: dict[str, float] = {"USD": 1.0}
    for sym in ("ETH/USD", "ADA/USD", "BTC/USD", "UNI/USD"):
        asset = sym.split("/")[0]
        usd_prices[asset] = float(data.fetch_ticker(sym))

    tracked = ("ETH", "ADA", "BTC", "USD", "UNI", "ATOM")
    holdings = {a: live.balance(a) for a in tracked if live.balance(a) > 0}
    portfolio = sum(
        holdings.get(a, 0) * usd_prices.get(a, 1.0 if a == "USD" else 0.0)
        for a in holdings
    )

    print("=== LIVE BALANCES ===")
    for asset, qty in sorted(holdings.items()):
        usd = qty * usd_prices.get(asset, 1.0 if asset == "USD" else 0.0)
        print(f"  {asset}: {qty:.6f} (${usd:.2f})")
    print(f"  PORTFOLIO USD: ${portfolio:.2f}")
    print(
        f"  LIVE: enabled={settings.live_enabled} mirror={settings.live_mirror_paper} "
        f"max=${settings.live_max_usd_per_trade}/trade allowed={settings.live_allowed_assets}"
    )

    candles = data.fetch_all_candles()
    composite = build_orchestrator(settings)
    result = composite.evaluate(
        candles, usd_prices, holdings, risk=None, markets=markets, context=None
    )

    intent_map: dict[str, tuple[float, float, str]] = {}
    for intent in result.intents:
        key = f"{intent.from_asset}->{intent.to_asset}"
        gross = intent.gross_return_pct or intent.edge
        intent_map[key] = (gross, intent.edge, intent.strategy_name or "?")

    opp_map: dict[str, tuple[float, str]] = {}
    for opp in result.opportunities:
        key = f"{opp.from_asset}->{opp.to_asset}"
        opp_map[key] = (opp.edge, opp.category)

    routes: list[dict] = []
    probe_assets = ("ETH", "ADA", "BTC", "USD")
    for from_asset in probe_assets:
        for to_asset in probe_assets:
            if from_asset == to_asset:
                continue
            route = markets.find_path(from_asset, to_asset, max_hops=1)
            if not route:
                continue
            key = f"{from_asset}->{to_asset}"
            if key in intent_map:
                gross, _, strat = intent_map[key]
            elif key in opp_map:
                gross, strat = opp_map[key]
            else:
                gross, strat = 0.0, "no_signal"
            fee_pct = fee_engine.compounded_fee_pct(route.symbols)
            slip = settings.slippage_buffer_pct * max(1, route.hops)
            net = gross - fee_pct - slip
            routes.append(
                {
                    "route": key,
                    "symbols": route.symbols,
                    "gross_pct": gross,
                    "fee_pct": fee_pct,
                    "slip_pct": slip,
                    "net_pct": net,
                    "positive": net > 0,
                    "strat": strat,
                }
            )

    routes.sort(key=lambda r: r["net_pct"], reverse=True)
    print("\n=== ROUTE PROBE (single-hop among ETH/ADA/BTC/USD) ===")
    hdr = f"{'Route':<12} {'Gross':>8} {'Fees':>8} {'Slip':>8} {'Net':>8} {'OK':>4} Strategy"
    print(hdr)
    for r in routes:
        ok = "YES" if r["positive"] else "no"
        print(
            f"{r['route']:<12} {r['gross_pct']:+.4f} {r['fee_pct']:.4f} "
            f"{r['slip_pct']:.4f} {r['net_pct']:+.4f} {ok:>4} {r['strat']}"
        )

    print("\n=== OFFENSIVE STRATEGY INTENTS (preflight) ===")
    for intent in result.intents:
        if intent.is_defensive:
            continue
        route = markets.find_path(intent.from_asset, intent.to_asset, max_hops=1)
        if not route:
            continue
        pf = preflight.validate(
            intent,
            route_symbols=route.symbols,
            hops=route.hops,
            is_defensive=False,
        )
        print(
            f"  {intent.from_asset}->{intent.to_asset} "
            f"gross={pf.gross_return_pct:+.4f} net={pf.net_return_pct:+.4f} "
            f"allowed={pf.allowed} [{intent.strategy_name}]"
        )

    positive = [r for r in routes if r["positive"]]
    print(f"\nPOSITIVE ROUTES NOW: {len(positive)}")
    for r in positive[:5]:
        print(f"  {r['route']} net={r['net_pct']:+.4%} via {r['symbols']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
