"""Strategy A — triangular (3-leg) cross-pair arbitrage scanner."""

from __future__ import annotations

import itertools
import logging
from typing import TYPE_CHECKING

from bot.strategies.base import Signal, Strategy, StrategyContext, StrategyResult, TradeIntent, RotationOption
from config import Settings

if TYPE_CHECKING:
    from bot.markets import MarketRegistry
    from bot.risk import RiskManager

logger = logging.getLogger(__name__)


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
    ) -> tuple[float, str, str, str] | None:
        a, b, c = assets
        route_ab = markets.find_path(a, b)
        route_bc = markets.find_path(b, c)
        route_ca = markets.find_path(c, a)
        if not route_ab or not route_bc or not route_ca:
            return None

        symbols = route_ab.symbols + route_bc.symbols + route_ca.symbols
        if any(pair_prices.get(s, 0.0) <= 0 for s in symbols):
            return None

        start = 1.0
        amt = self._simulate_route(start, route_ab, pair_prices, self.fee_rate)
        amt = self._simulate_route(amt, route_bc, pair_prices, self.fee_rate)
        amt = self._simulate_route(amt, route_ca, pair_prices, self.fee_rate)
        gross = amt - start
        path = f"{a}->{b}->{c}->{a}"
        return gross, path, a, b

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

        best: tuple[float, str, str, str] | None = None
        for combo in itertools.permutations(assets, 3):
            if held and combo[0] not in held:
                continue
            result = self._loop_profit(combo, markets, pair_prices)
            if result and (best is None or result[0] > best[0]):
                best = result

        intents: list[TradeIntent] = []
        opportunities: list[RotationOption] = []
        blocked: list[str] = []

        if best and best[0] > min_net:
            gross, path, from_a, to_b = best
            intents.append(
                TradeIntent(
                    from_asset=from_a,
                    to_asset=to_b,
                    reason=f"triangular arb leg 1/3 — loop {path} gross {gross:+.4f}",
                    size_pct=self.trade_size_pct,
                    edge=gross,
                    gross_return_pct=gross,
                    is_held_swap=True,
                    strategy_name=self.name,
                )
            )
            opportunities.append(
                RotationOption(
                    from_asset=from_a,
                    to_asset=to_b,
                    edge=gross,
                    required_edge=min_net,
                    category="triangular_arb",
                    path=path,
                    hops=3,
                )
            )
        elif best:
            blocked.append(
                f"Triangular best loop {best[1]} gross {best[0]:+.4f} below min net {min_net:+.4f}"
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
