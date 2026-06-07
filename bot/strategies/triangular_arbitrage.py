"""Strategy A — triangular (3-leg) cross-pair arbitrage scanner."""

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from bot.markets import TradeRoute
from bot.strategies.base import Signal, Strategy, StrategyContext, StrategyResult, TradeIntent, RotationOption
from config import Settings

if TYPE_CHECKING:
    from bot.markets import MarketRegistry
    from bot.risk import RiskManager

logger = logging.getLogger(__name__)


@dataclass
class LoopResult:
    """A scored, fully-closed triangular loop ready to execute atomically."""

    net_est: float          # net loop return after static fee_rate (emit gate)
    gross_prefee: float     # pre-fee loop return (handed to pre-flight)
    path: str               # human-readable A->B->C->A
    start_asset: str        # the asset the loop starts and ends on
    route: TradeRoute       # the concatenated multi-leg route


class TriangularArbitrageStrategy(Strategy):
    """
    Detect profitable A -> B -> C -> A loops using live pair prices.
    Emits the first leg as an IOC-style intent when net loop profit exceeds fees.
    """

    name = "triangular_arbitrage"

    def __init__(self, settings: Settings):
        self.watch_assets = settings.watch_assets
        self.trade_size_pct = settings.trade_size_pct
        self.fee_rate = settings.fee_rate
        self.min_net_profit_pct = settings.min_net_profit_pct
        self.dust_usd = settings.dust_usd

    def _simulate_leg(
        self, amount: float, side: Signal, price: float, fee_rate: float
    ) -> float:
        if amount <= 0 or price <= 0:
            return 0.0
        if side == Signal.BUY:
            net_quote = amount * (1.0 - fee_rate)
            return net_quote / price
        gross = amount * price
        return gross * (1.0 - fee_rate)

    def _simulate_route(
        self,
        start_amount: float,
        route,
        prices: dict[str, float],
        fee_rate: float,
    ) -> float:
        amount = start_amount
        for leg in route.legs:
            price = prices.get(leg.pair.symbol, 0.0)
            amount = self._simulate_leg(amount, leg.side, price, fee_rate)
            if amount <= 0:
                return 0.0
        return amount

    def _loop_profit(
        self,
        assets: tuple[str, str, str],
        markets: MarketRegistry,
        pair_prices: dict[str, float],
    ) -> "LoopResult | None":
        a, b, c = assets
        route_ab = markets.find_path(a, b)
        route_bc = markets.find_path(b, c)
        route_ca = markets.find_path(c, a)
        if not route_ab or not route_bc or not route_ca:
            return None

        symbols = route_ab.symbols + route_bc.symbols + route_ca.symbols
        if any(pair_prices.get(s, 0.0) <= 0 for s in symbols):
            return None

        # The full closed loop as a single atomic route (A->B->C->A). The
        # engine executes exactly this, so the loop either completes in one
        # shot or does not fire — never just leg 1.
        loop = TradeRoute(legs=route_ab.legs + route_bc.legs + route_ca.legs)
        if loop.legs[0].from_asset != a or loop.legs[-1].to_asset != a:
            return None  # not a genuine closed loop; refuse to trade

        start = 1.0
        # Net-of-fee estimate (using the strategy's static fee_rate) only
        # decides whether the opportunity is worth emitting; the engine's
        # pre-flight re-checks net against LIVE fees before any fill.
        net_amt = self._simulate_route(start, loop, pair_prices, self.fee_rate)
        net_est = net_amt - start
        # Pre-fee gross loop return — this is what we hand to pre-flight as
        # gross_return_pct so it can subtract the *real* compounded fees.
        gross_amt = self._simulate_route(start, loop, pair_prices, 0.0)
        gross_prefee = gross_amt - start
        path = f"{a}->{b}->{c}->{a}"
        return LoopResult(
            net_est=net_est,
            gross_prefee=gross_prefee,
            path=path,
            start_asset=a,
            route=loop,
        )

    def evaluate(
        self,
        candles,
        prices: dict[str, float],
        holdings: dict[str, float],
        risk: RiskManager | None = None,
        markets: MarketRegistry | None = None,
        context: StrategyContext | None = None,
    ) -> StrategyResult:
        empty = StrategyResult(
            signals={},
            scores={},
            reasons={},
            sizes={},
            idle_reason="Triangular arb — no markets",
        )
        if not markets:
            return empty

        pair_prices = context.pair_prices if context else {}
        if not pair_prices:
            return StrategyResult(
                signals={},
                scores={},
                reasons={},
                sizes={},
                idle_reason="Triangular arb — waiting for pair prices",
            )

        if risk and risk.is_paused():
            return StrategyResult(
                signals={},
                scores={},
                reasons={},
                sizes={},
                idle_reason=risk.pause_status(),
            )

        min_net = risk.effective_min_net_profit() if risk else self.min_net_profit_pct

        assets = [a for a in self.watch_assets if a != "USD"]
        held = [
            a
            for a, q in holdings.items()
            if a in assets and q > 0 and q * prices.get(a, 0.0) >= self.dust_usd
        ]
        if not held:
            held = list(assets[:3])

        best: LoopResult | None = None
        loops_scanned = 0
        loops_no_market = 0
        loops_below_min = 0

        for combo in itertools.permutations(assets, 3):
            if held and combo[0] not in held:
                continue
            loops_scanned += 1
            result = self._loop_profit(combo, markets, pair_prices)
            if result is None:
                loops_no_market += 1
                continue
            if result.net_est <= min_net:
                loops_below_min += 1
            if result and (best is None or result.net_est > best.net_est):
                best = result

        logger.debug(
            "triangular_arb scan: %d loops checked — %d no-market, %d below-min-net (%.4f)",
            loops_scanned,
            loops_no_market,
            loops_below_min,
            min_net,
        )

        intents: list[TradeIntent] = []
        opportunities: list[RotationOption] = []
        blocked: list[str] = []

        if best and best.net_est > min_net:
            logger.debug(
                "triangular_arb: best loop %s gross %+.4f est_net %+.4f → emitting intent",
                best.path,
                best.gross_prefee,
                best.net_est,
            )
            # Emit the WHOLE closed loop as one atomic intent. from_asset ==
            # to_asset == start_asset, and the pre-built route carries all three
            # legs so the engine completes the loop in a single execution rather
            # than firing leg 1 and stranding an intermediate coin.
            intents.append(
                TradeIntent(
                    from_asset=best.start_asset,
                    to_asset=best.start_asset,
                    reason=(
                        f"triangular arb loop {best.path} — "
                        f"gross {best.gross_prefee:+.4f}, est net {best.net_est:+.4f}"
                    ),
                    size_pct=self.trade_size_pct,
                    edge=best.net_est,
                    gross_return_pct=best.gross_prefee,
                    is_held_swap=True,
                    strategy_name=self.name,
                    route=best.route,
                )
            )
            opportunities.append(
                RotationOption(
                    from_asset=best.start_asset,
                    to_asset=best.start_asset,
                    edge=best.net_est,
                    required_edge=min_net,
                    category="triangular_arb",
                    path=best.path,
                    hops=best.route.hops,
                )
            )
        elif best:
            blocked.append(
                f"Triangular best loop {best.path} est net {best.net_est:+.4f} "
                f"below min net {min_net:+.4f}"
            )

        return StrategyResult(
            signals={},
            scores={},
            reasons={},
            sizes={},
            intents=intents,
            idle_reason="Scanning triangular loops" if not intents else "",
            blocked=blocked,
            opportunities=opportunities,
        )
