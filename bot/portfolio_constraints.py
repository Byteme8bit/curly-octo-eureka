"""Portfolio allocation rules — ETH floor, alt caps, and crypto/equity bucket targets."""

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


@dataclass(frozen=True)
class BucketAllocation:
    """Crypto vs equity vs cash split as fractions of total portfolio."""

    equity_pct: float
    crypto_pct: float
    usd_pct: float
    portfolio_usd: float


class PortfolioConstraints:
    """
    - Keep at least min_eth_reserve ETH at all times.
    - Alts (not ETH/BTC/USD) capped at max_alt_allocation unless strategy exception.
    - Optional 50/50 bucket targets: trim overweight crypto to USD for equity DCA;
      block equity→crypto during accumulation unless severely overweight equity.
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
        target_equity_allocation_pct: float = 0.50,
        target_crypto_allocation_pct: float = 0.50,
        max_equity_bucket_pct: float = 0.55,
        max_crypto_bucket_pct: float = 0.55,
        equity_accumulation_phase: bool = False,
        equity_dca_priority: bool = False,
        equity_accumulation_min_pct: float = 0.45,
        equity_severe_overweight_pct: float = 0.60,
        max_equity_positions: int = 0,
        dust_usd: float = 5.0,
    ):
        self.min_eth_reserve = min_eth_reserve
        self.max_alt_allocation_pct = max_alt_allocation_pct
        self.min_usd_trade = min_usd_trade
        self.overweight_edge_multiplier = overweight_edge_multiplier
        self.strict_eth_floor = strict_eth_floor
        self.equity_assets = equity_assets or frozenset()
        self.max_equity_allocation_pct = max_equity_allocation_pct
        self.target_equity_allocation_pct = target_equity_allocation_pct
        self.target_crypto_allocation_pct = target_crypto_allocation_pct
        self.max_equity_bucket_pct = max_equity_bucket_pct
        self.max_crypto_bucket_pct = max_crypto_bucket_pct
        self.equity_accumulation_phase = equity_accumulation_phase
        self.equity_dca_priority = equity_dca_priority
        self.equity_accumulation_min_pct = equity_accumulation_min_pct
        self.equity_severe_overweight_pct = equity_severe_overweight_pct
        self.max_equity_positions = max_equity_positions
        self.dust_usd = dust_usd

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

    def bucket_allocation(
        self, holdings: dict[str, float], prices: dict[str, float]
    ) -> BucketAllocation:
        portfolio = self.portfolio_value(holdings, prices)
        if portfolio <= 0:
            return BucketAllocation(0.0, 0.0, 0.0, 0.0)
        usd = self._position_usd("USD", holdings, prices)
        equity_usd = sum(
            self._position_usd(asset, holdings, prices)
            for asset in self.equity_assets
            if holdings.get(asset, 0.0) > 0
        )
        crypto_usd = max(0.0, portfolio - usd - equity_usd)
        return BucketAllocation(
            equity_pct=equity_usd / portfolio,
            crypto_pct=crypto_usd / portfolio,
            usd_pct=usd / portfolio,
            portfolio_usd=portfolio,
        )

    def equity_bucket_pct(self, holdings: dict[str, float], prices: dict[str, float]) -> float:
        return self.bucket_allocation(holdings, prices).equity_pct

    def crypto_bucket_pct(self, holdings: dict[str, float], prices: dict[str, float]) -> float:
        return self.bucket_allocation(holdings, prices).crypto_pct

    def in_equity_accumulation(
        self, holdings: dict[str, float], prices: dict[str, float]
    ) -> bool:
        """True while equity bucket is below target — DCA and defensive crypto trims apply."""
        if not self.equity_assets:
            return False
        equity_pct = self.equity_bucket_pct(holdings, prices)
        if equity_pct < self.equity_accumulation_min_pct:
            return True
        if self.equity_accumulation_phase and equity_pct < self.target_equity_allocation_pct:
            return True
        return False

    def format_allocation_line(
        self, holdings: dict[str, float], prices: dict[str, float]
    ) -> str:
        buckets = self.bucket_allocation(holdings, prices)
        if buckets.portfolio_usd <= 0:
            return ""
        phase = "accumulation" if self.in_equity_accumulation(holdings, prices) else "balanced"
        return (
            f"Allocation  crypto {buckets.crypto_pct:.1%} / equity {buckets.equity_pct:.1%} "
            f"(target {self.target_crypto_allocation_pct:.0%}/{self.target_equity_allocation_pct:.0%}, "
            f"{phase})"
        )

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
            if index == 0 and from_bal <= 0:
                return ConstraintResult(
                    False,
                    size_pct,
                    f"Route leg {index + 1} insufficient {from_asset} balance",
                )
            if from_bal <= 0:
                continue
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
        if intent.strategy_name in ("stat_arb", "triangular_arbitrage", "cross_momentum") and edge >= hurdle:
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

    def _blocks_equity_to_crypto(
        self,
        intent: TradeIntent,
        holdings: dict[str, float],
        prices: dict[str, float],
    ) -> ConstraintResult | None:
        if not self.in_equity_accumulation(holdings, prices):
            return None
        if not _is_equity(intent.from_asset, self.equity_assets):
            return None
        if _is_equity(intent.to_asset, self.equity_assets) or intent.to_asset == "USD":
            return None
        equity_pct = self.equity_bucket_pct(holdings, prices)
        if equity_pct >= self.equity_severe_overweight_pct:
            return None
        return ConstraintResult(
            False,
            intent.size_pct,
            (
                f"Equity accumulation — cannot sell {intent.from_asset} for "
                f"{intent.to_asset} (equity {equity_pct:.1%}, target "
                f"{self.target_equity_allocation_pct:.0%})"
            ),
        )

    def validate_intent(
        self,
        intent: TradeIntent,
        holdings: dict[str, float],
        prices: dict[str, float],
        *,
        required_edge: float,
    ) -> ConstraintResult:
        size_pct = max(0.0, min(1.0, intent.size_pct))

        accumulation_block = self._blocks_equity_to_crypto(intent, holdings, prices)
        if accumulation_block is not None and not intent.is_defensive:
            return accumulation_block

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
            if (
                self.max_equity_positions > 0
                and _is_equity(intent.to_asset, self.equity_assets)
                and holdings.get(intent.to_asset, 0.0) * prices.get(intent.to_asset, 0.0)
                < self.dust_usd
            ):
                held = sum(
                    1
                    for a in self.equity_assets
                    if holdings.get(a, 0.0) * prices.get(a, 0.0) >= self.dust_usd
                )
                if held >= self.max_equity_positions:
                    return ConstraintResult(
                        False,
                        size_pct,
                        (
                            f"Equity positions — already holding {held} xStocks "
                            f"(max {self.max_equity_positions})"
                        ),
                    )
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

        if (
            self.equity_assets
            and not intent.is_defensive
            and not _is_equity(intent.to_asset, self.equity_assets)
            and intent.to_asset != "USD"
        ):
            buckets = self.bucket_allocation(holdings, prices)
            projected_crypto = buckets.crypto_pct + (
                trade_usd / buckets.portfolio_usd if buckets.portfolio_usd > 0 else 0.0
            )
            if (
                projected_crypto > self.max_crypto_bucket_pct
                and not self.allows_alt_overweight(intent, required_edge=required_edge)
            ):
                return ConstraintResult(
                    False,
                    size_pct,
                    (
                        f"Crypto bucket — would reach {projected_crypto:.1%} "
                        f"(max {self.max_crypto_bucket_pct:.0%} offensive budget)"
                    ),
                )

        return ConstraintResult(True, size_pct, "")

    def _trim_crypto_bucket_intents(
        self,
        holdings: dict[str, float],
        prices: dict[str, float],
        find_path,
    ) -> list[TradeIntent]:
        """When crypto bucket exceeds cap, sell alts (then ETH above reserve) to USD for equity DCA."""
        buckets = self.bucket_allocation(holdings, prices)
        if buckets.portfolio_usd <= 0 or buckets.crypto_pct <= self.max_crypto_bucket_pct:
            return []

        target_crypto_usd = buckets.portfolio_usd * self.max_crypto_bucket_pct
        current_crypto_usd = buckets.portfolio_usd * buckets.crypto_pct
        trim_usd = current_crypto_usd - target_crypto_usd
        if trim_usd < self.min_usd_trade:
            return []

        if not find_path("ETH", "USD") and not any(
            find_path(a, "USD")
            for a, q in holdings.items()
            if q > 0 and a not in CORE_UNCAPPED and not _is_equity(a, self.equity_assets)
        ):
            return []

        candidates: list[tuple[float, str]] = []
        for asset, qty in holdings.items():
            if qty <= 0 or asset in CORE_UNCAPPED or _is_equity(asset, self.equity_assets):
                continue
            usd_val = self._position_usd(asset, holdings, prices)
            if usd_val >= self.min_usd_trade and find_path(asset, "USD"):
                candidates.append((usd_val, asset))
        candidates.sort(reverse=True)

        intents: list[TradeIntent] = []
        remaining = trim_usd
        for _, asset in candidates:
            if remaining < self.min_usd_trade:
                break
            position_usd = self._position_usd(asset, holdings, prices)
            sell_usd = min(remaining, position_usd * 0.5)
            if sell_usd < self.min_usd_trade:
                continue
            size_pct = min(1.0, sell_usd / position_usd)
            intents.append(
                TradeIntent(
                    from_asset=asset,
                    to_asset="USD",
                    reason=(
                        f"crypto bucket — trim {asset} to USD "
                        f"(crypto {buckets.crypto_pct:.1%} > {self.max_crypto_bucket_pct:.0%}) "
                        f"for equity DCA funding"
                    ),
                    size_pct=size_pct,
                    edge=0.0,
                    is_defensive=True,
                    strategy_name="portfolio_constraints",
                )
            )
            remaining -= sell_usd

        if remaining >= self.min_usd_trade:
            eth_bal = holdings.get("ETH", 0.0)
            eth_usd = eth_bal * prices.get("ETH", 0.0)
            sellable_eth = max(0.0, eth_bal - self.min_eth_reserve)
            sellable_usd = sellable_eth * prices.get("ETH", 0.0)
            if sellable_usd >= self.min_usd_trade and find_path("ETH", "USD"):
                sell_usd = min(remaining, sellable_usd * 0.5)
                size_pct = min(1.0, sell_usd / eth_usd) if eth_usd > 0 else 0.0
                if size_pct > 0:
                    intents.append(
                        TradeIntent(
                            from_asset="ETH",
                            to_asset="USD",
                            reason=(
                                f"crypto bucket — trim ETH to USD "
                                f"(crypto {buckets.crypto_pct:.1%} > {self.max_crypto_bucket_pct:.0%})"
                            ),
                            size_pct=size_pct,
                            edge=0.0,
                            is_defensive=True,
                            strategy_name="portfolio_constraints",
                        )
                    )
        return intents

    def trim_overweight_intents(
        self,
        holdings: dict[str, float],
        prices: dict[str, float],
        find_path,
    ) -> list[TradeIntent]:
        """Defensive trims when alts/equities exceed caps or crypto bucket is overweight."""
        portfolio = self.portfolio_value(holdings, prices)
        if portfolio <= 0:
            return []

        intents: list[TradeIntent] = []
        intents.extend(self._trim_crypto_bucket_intents(holdings, prices, find_path))

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
                if self.in_equity_accumulation(holdings, prices):
                    equity_bucket = self.equity_bucket_pct(holdings, prices)
                    if equity_bucket < self.max_equity_bucket_pct:
                        continue
                target = "USD"
            else:
                if self.in_equity_accumulation(holdings, prices) and find_path(asset, "USD"):
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
