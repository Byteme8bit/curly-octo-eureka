"""Portfolio allocation rules — ETH floor and altcoin concentration caps."""

from __future__ import annotations

from dataclasses import dataclass

from bot.markets import TradeRoute
from bot.strategies.base import Signal, TradeIntent

CORE_UNCAPPED = frozenset({"ETH", "BTC", "USD"})


def _is_equity(asset: str, equity_assets: frozenset[str]) -> bool:
    return asset in equity_assets


@dataclass(frozen=True)
class ConstraintResult:
    allowed: bool
    size_pct: float
    reason: str = ""


class PortfolioConstraints:
    """
    - Keep at least min_eth_reserve ETH at all times.
    - Alts (not ETH/BTC/USD) capped at max_alt_allocation unless strategy exception.
    """

    def __init__(
        self,
        min_eth_reserve: float,
        max_alt_allocation_pct: float,
        min_usd_trade: float,
        overweight_edge_multiplier: float = 1.25,
        *,
        strict_eth_floor: bool = False,
        equity_assets: frozenset[str] | None = None,
        max_equity_allocation_pct: float = 0.15,
    ):
        self.min_eth_reserve = min_eth_reserve
        self.max_alt_allocation_pct = max_alt_allocation_pct
        self.min_usd_trade = min_usd_trade
        self.overweight_edge_multiplier = overweight_edge_multiplier
        self.strict_eth_floor = strict_eth_floor
        self.equity_assets = equity_assets or frozenset()
        self.max_equity_allocation_pct = max_equity_allocation_pct

    def portfolio_value(self, holdings: dict[str, float], prices: dict[str, float]) -> float:
        total = holdings.get("USD", 0.0)
        for asset, qty in holdings.items():
            if asset != "USD" and qty > 0:
                total += qty * prices.get(asset, 0.0)
        return total

    def allocation_pct(
        self, asset: str, holdings: dict[str, float], prices: dict[str, float]
    ) -> float:
        portfolio = self.portfolio_value(holdings, prices)
        if portfolio <= 0:
            return 0.0
        qty = holdings.get(asset, 0.0)
        if asset == "USD":
            return qty / portfolio
        return (qty * prices.get(asset, 0.0)) / portfolio

    def _position_usd(self, asset: str, holdings: dict[str, float], prices: dict[str, float]) -> float:
        qty = holdings.get(asset, 0.0)
        if asset == "USD":
            return qty
        return qty * prices.get(asset, 0.0)

    def clamp_eth_sell_size(self, from_asset: str, size_pct: float, holdings: dict[str, float]) -> float:
        if from_asset != "ETH":
            return size_pct
        balance = holdings.get("ETH", 0.0)
        if balance <= self.min_eth_reserve:
            return 0.0
        max_sell = balance - self.min_eth_reserve
        max_pct = max_sell / balance
        return max(0.0, min(size_pct, max_pct))

    def check_route_eth_floor(
        self,
        route: TradeRoute,
        holdings: dict[str, float],
        size_pct: float,
    ) -> ConstraintResult:
        """Simulate route legs; block if any ETH sell drops below the reserve."""
        balances = {k: float(v) for k, v in holdings.items()}
        floor = self.min_eth_reserve
        for index, leg in enumerate(route.legs):
            leg_pct = size_pct if index == 0 else 1.0
            from_asset = leg.from_asset
            from_bal = balances.get(from_asset, 0.0)
            if from_bal <= 0:
                return ConstraintResult(
                    False,
                    size_pct,
                    f"Route leg {index + 1} insufficient {from_asset} balance",
                )
            trade_qty = from_bal * leg_pct
            balances[from_asset] = from_bal - trade_qty
            if leg.from_asset == "ETH":
                remaining = balances.get("ETH", 0.0)
                if remaining < floor - 1e-9:
                    return ConstraintResult(
                        False,
                        size_pct,
                        (
                            f"ETH reserve — route {route.path} would leave "
                            f"{remaining:.4f} ETH (floor {floor:.2f})"
                        ),
                    )
            if leg.to_asset == "ETH" and leg.side == Signal.BUY:
                balances["ETH"] = balances.get("ETH", 0.0) + trade_qty
        return ConstraintResult(True, size_pct, "")

    def allows_alt_overweight(self, intent: TradeIntent, *, required_edge: float) -> bool:
        """Strategy-backed exception to the alt concentration cap."""
        if intent.to_asset in CORE_UNCAPPED:
            return True
        if intent.is_defensive:
            return False
        edge = intent.gross_return_pct or intent.edge
        hurdle = max(required_edge, 0.0001) * self.overweight_edge_multiplier
        if intent.require_leader_stable and edge >= hurdle:
            return True
        if intent.is_expansion and edge >= hurdle * 1.2:
            return True
        if intent.strategy_name in ("stat_arb", "triangular_arbitrage") and edge >= hurdle:
            return True
        reason = intent.reason.lower()
        if any(k in reason for k in ("leader", "outpacing", "stat arb", "triangular")):
            if edge >= hurdle:
                return True
        return False

    def projected_allocation(
        self,
        asset: str,
        holdings: dict[str, float],
        prices: dict[str, float],
        *,
        from_asset: str,
        to_asset: str,
        trade_usd: float,
    ) -> float:
        portfolio = self.portfolio_value(holdings, prices)
        if portfolio <= 0:
            return 0.0
        values: dict[str, float] = {}
        for a, qty in holdings.items():
            values[a] = self._position_usd(a, holdings, prices)
        values[from_asset] = max(0.0, values.get(from_asset, 0.0) - trade_usd)
        values[to_asset] = values.get(to_asset, 0.0) + trade_usd
        return values.get(asset, 0.0) / portfolio

    def validate_intent(
        self,
        intent: TradeIntent,
        holdings: dict[str, float],
        prices: dict[str, float],
        *,
        required_edge: float,
    ) -> ConstraintResult:
        size_pct = max(0.0, min(1.0, intent.size_pct))

        # Closed-loop intents (from_asset == to_asset, e.g. ETH→UNI→AAVE→ETH) borrow
        # ETH as an intermediate and return it atomically — net ETH balance is unchanged
        # after the loop, so the reserve check must NOT deduct from the holding (paper).
        # Live mode uses strict_eth_floor: any ETH leg that sells must stay above reserve.
        is_closed_loop = intent.from_asset == intent.to_asset
        if self.strict_eth_floor or not is_closed_loop:
            size_pct = self.clamp_eth_sell_size(intent.from_asset, size_pct, holdings)

        if intent.from_asset == "ETH" and size_pct <= 0 and (
            not is_closed_loop or self.strict_eth_floor
        ):
            reserve = self.min_eth_reserve
            bal = holdings.get("ETH", 0.0)
            return ConstraintResult(
                False,
                0.0,
                f"ETH reserve — cannot sell below {reserve:.2f} ETH (holding {bal:.4f})",
            )

        trade_usd = self._position_usd(intent.from_asset, holdings, prices) * size_pct
        if trade_usd < self.min_usd_trade and not intent.is_defensive:
            return ConstraintResult(False, size_pct, "Trade size below minimum after ETH reserve clamp")

        if intent.to_asset not in CORE_UNCAPPED and not intent.is_defensive:
            cap = self.max_equity_allocation_pct if _is_equity(
                intent.to_asset, self.equity_assets
            ) else self.max_alt_allocation_pct
            cap_label = "Equity" if _is_equity(intent.to_asset, self.equity_assets) else "Alt"
            projected = self.projected_allocation(
                intent.to_asset,
                holdings,
                prices,
                from_asset=intent.from_asset,
                to_asset=intent.to_asset,
                trade_usd=trade_usd,
            )
            if projected > cap:
                if not self.allows_alt_overweight(intent, required_edge=required_edge):
                    return ConstraintResult(
                        False,
                        size_pct,
                        (
                            f"{cap_label} cap — {intent.to_asset} would reach {projected:.1%} "
                            f"(max {cap:.0%} without strategy exception)"
                        ),
                    )
                current = self.allocation_pct(intent.to_asset, holdings, prices)
                if current >= cap:
                    return ConstraintResult(
                        False,
                        size_pct,
                        (
                            f"{cap_label} cap — {intent.to_asset} already at {current:.1%}; "
                            f"need trim before adding (exception not applied)"
                        ),
                    )

        return ConstraintResult(True, size_pct, "")

    def trim_overweight_intents(
        self,
        holdings: dict[str, float],
        prices: dict[str, float],
        find_path,
    ) -> list[TradeIntent]:
        """Defensive trims when alts exceed max allocation without active strategy hold."""
        portfolio = self.portfolio_value(holdings, prices)
        if portfolio <= 0:
            return []

        intents: list[TradeIntent] = []
        for asset, qty in holdings.items():
            if asset in CORE_UNCAPPED or qty <= 0:
                continue
            cap = self.max_equity_allocation_pct if _is_equity(
                asset, self.equity_assets
            ) else self.max_alt_allocation_pct
            alloc = self.allocation_pct(asset, holdings, prices)
            if alloc <= cap:
                continue

            position_usd = self._position_usd(asset, holdings, prices)
            target_usd = portfolio * cap
            trim_usd = position_usd - target_usd
            if trim_usd < self.min_usd_trade:
                continue

            if _is_equity(asset, self.equity_assets):
                target = "USD"
            else:
                target = "ETH" if find_path(asset, "ETH") else "BTC"
            if not find_path(asset, target):
                continue

            size_pct = min(0.5, trim_usd / position_usd)
            cap_label = "equity" if _is_equity(asset, self.equity_assets) else "alt"
            intents.append(
                TradeIntent(
                    from_asset=asset,
                    to_asset=target,
                    reason=(
                        f"portfolio cap — trim {asset} from {alloc:.1%} to "
                        f"{cap:.0%} max ({cap_label} concentration)"
                    ),
                    size_pct=size_pct,
                    edge=0.0,
                    is_defensive=True,
                    strategy_name="portfolio_constraints",
                )
            )
        return intents
