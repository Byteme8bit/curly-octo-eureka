import pandas as pd

from dataclasses import dataclass

from typing import TYPE_CHECKING



from bot.risk import RiskManager

from bot.funding_priority import funding_rank

from bot.strategies.base import Signal, Strategy, StrategyResult, TradeIntent, RotationOption

from config import Settings



if TYPE_CHECKING:

    from bot.markets import MarketRegistry





@dataclass

class _RotationCandidate:

    from_asset: str

    to_asset: str

    edge: float

    required: float

    net_edge: float

    diversify_score: float

    hops: int

    path: str

    category: str

    size_pct: float

    is_defensive: bool

    is_held_swap: bool

    is_expansion: bool

    require_leader_stable: bool

    reason: str





class MomentumRotationStrategy(Strategy):

    """

    Holdings-aware momentum strategy with open diversification.



    Prefers spreading into new and underweight coins via a soft scoring bonus,

    but does not cap how many assets the portfolio can hold.

    """



    name = "momentum_rotation"



    def __init__(self, settings: Settings):

        self.watch_assets = settings.watch_assets

        self.usd_symbols = settings.usd_symbols

        self.ema_fast = settings.ema_fast

        self.ema_slow = settings.ema_slow

        self.momentum_sell = settings.momentum_sell

        self.trade_size_pct = settings.trade_size_pct

        self.expansion_size_pct = settings.expansion_size_pct

        self.min_usd_trade = settings.min_usd_trade

        self.diversify_bonus = settings.diversify_bonus

        self.core_assets = set(settings.core_assets)

        self.preferred_start_assets = settings.preferred_start_assets

        self.dust_usd = settings.dust_usd
        self.symbol_assets = settings.symbol_assets
        self.asset_usd_symbols = settings.asset_usd_symbols



    def _momentum_score(self, candles: pd.DataFrame) -> float:

        close = candles["close"]

        if len(close) < self.ema_slow:

            return 0.0

        fast = close.ewm(span=self.ema_fast, adjust=False).mean().iloc[-1]

        slow = close.ewm(span=self.ema_slow, adjust=False).mean().iloc[-1]

        if slow == 0:

            return 0.0

        return float((fast - slow) / slow)



    def _held_assets(self, holdings: dict[str, float]) -> list[str]:

        return [a for a, q in holdings.items() if a != "USD" and q > 0]



    def _asset_score(self, asset: str, scores: dict[str, float]) -> float:

        symbol = self.asset_usd_symbols.get(asset)

        return scores.get(symbol, 0.0) if symbol else 0.0



    def _portfolio_value(self, holdings: dict[str, float], prices: dict[str, float]) -> float:

        total = holdings.get("USD", 0.0)

        for asset, qty in holdings.items():

            if asset != "USD" and qty > 0:

                total += qty * prices.get(asset, 0.0)

        return total



    def _position_usd(self, asset: str, holdings: dict[str, float], prices: dict[str, float]) -> float:

        qty = holdings.get(asset, 0.0)

        if asset == "USD":

            return qty

        return qty * prices.get(asset, 0.0) if qty > 0 else 0.0



    def _allocation_pct(self, asset: str, holdings: dict[str, float], prices: dict[str, float]) -> float:

        portfolio = self._portfolio_value(holdings, prices)

        if portfolio <= 0:

            return 0.0

        return self._position_usd(asset, holdings, prices) / portfolio



    def _average_weight(self, holdings: dict[str, float]) -> float:

        held = self._held_assets(holdings)

        if not held:

            return 1.0 / max(1, len(self.watch_assets))

        return 1.0 / len(held)



    def _ranked_assets(self, scores: dict[str, float]) -> list[str]:

        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)

        return [self.symbol_assets[sym] for sym, _ in ranked]



    def _diversify_score(

        self,

        candidate: _RotationCandidate,

        holdings: dict[str, float],

        prices: dict[str, float],

    ) -> float:

        if candidate.net_edge < 0 and not candidate.is_defensive:

            return candidate.net_edge



        score = candidate.net_edge

        tgt_alloc = self._allocation_pct(candidate.to_asset, holdings, prices)

        avg_weight = self._average_weight(holdings)



        if candidate.to_asset not in self._held_assets(holdings):

            score += self.diversify_bonus * 2

        elif tgt_alloc < avg_weight * 0.5:

            score += self.diversify_bonus



        if tgt_alloc > avg_weight * 1.5:

            score -= (tgt_alloc - avg_weight) * 0.02



        return score



    def _route_requirements(

        self,

        from_asset: str,

        to_asset: str,

        held_assets: list[str],

        risk: RiskManager | None,

        markets: "MarketRegistry | None",

    ) -> tuple[int, float, str] | None:

        if not markets or not risk:

            return 1, risk.required_edge() if risk else 0.006, ""



        route = markets.find_path(from_asset, to_asset)

        if not route:

            return None



        is_held_swap = to_asset in held_assets

        required = risk.path_edge(route.hops, is_held_swap=is_held_swap)

        return route.hops, required, route.path



    def _viable_size_pct(

        self,

        asset: str,

        holdings: dict[str, float],

        prices: dict[str, float],

        base_pct: float,

    ) -> float:

        value = self._position_usd(asset, holdings, prices)

        if value <= 0:

            return 0.0

        if value * base_pct >= self.min_usd_trade:

            return base_pct

        needed = self.min_usd_trade / value

        return needed if needed <= 1.0 else 0.0



    def _category(

        self,

        source: str,

        target: str,

        held_assets: list[str],

        leader: str,

        holdings: dict[str, float],

        prices: dict[str, float],

    ) -> str:

        src_alloc = self._allocation_pct(source, holdings, prices)

        tgt_alloc = self._allocation_pct(target, holdings, prices)

        avg_weight = self._average_weight(holdings)

        if src_alloc > avg_weight * 2 and tgt_alloc < avg_weight:

            return "diversify"

        if target in held_assets:

            return "held_swap"

        if target == leader:

            return "leader_rotation"

        return "expansion"



    def _build_reason(

        self,

        source: str,

        target: str,

        src_score: float,

        tgt_score: float,

        edge: float,

        path: str,

        hops: int,

        category: str,

        is_defensive: bool,

        tgt_alloc: float,

    ) -> str:

        path_note = f" via {path.replace('->', ' -> ')}" if path and hops > 1 else ""

        if category == "diversify":

            return (

                f"diversifying - trimming {source} into {target} "

                f"({target} {tgt_score:+.4f} vs {source} {src_score:+.4f}, "

                f"{target} at {tgt_alloc:.0%} of portfolio){path_note}"

            )

        if is_defensive:

            return (

                f"mitigating losses - moving {source} into {target} "

                f"({target} {tgt_score:+.4f} vs {source} {src_score:+.4f}){path_note}"

            )

        if category == "expansion":

            return (

                f"expanding into {target} to drive gains - "

                f"{target} {tgt_score:+.4f} vs {source} {src_score:+.4f} "

                f"(edge {edge:+.4f} after fees){path_note}"

            )

        if category == "leader_rotation":

            return (

                f"driving gains - rotating {source} into {target} "

                f"({target} {tgt_score:+.4f} vs {source} {src_score:+.4f}){path_note}"

            )

        return (

            f"driving gains - {target} outpacing {source} "

            f"by {edge:+.4f} after fees{path_note}"

        )



    def _scan_rotations(

        self,

        held_assets: list[str],

        holdings: dict[str, float],

        prices: dict[str, float],

        scores: dict[str, float],

        leader_asset: str,

        risk: RiskManager | None,

        markets: "MarketRegistry | None",

    ) -> list[_RotationCandidate]:

        candidates: list[_RotationCandidate] = []

        avg_weight = self._average_weight(holdings)



        sources = sorted(

            held_assets,

            key=lambda a: (

                funding_rank(a, self.preferred_start_assets),

                -max(0.0, self._allocation_pct(a, holdings, prices) - avg_weight * 2),

                self._asset_score(a, scores),

                -self._position_usd(a, holdings, prices),

            ),

        )



        for source in sources:

            src_score = self._asset_score(source, scores)

            src_heavy = self._allocation_pct(source, holdings, prices) > avg_weight * 2



            for target in self.watch_assets:

                if target == source:

                    continue



                is_held_swap = target in held_assets

                is_expansion = not is_held_swap



                tgt_score = self._asset_score(target, scores)

                edge = tgt_score - src_score

                route_info = self._route_requirements(source, target, held_assets, risk, markets)

                if not route_info:

                    continue



                hops, required, path = route_info

                net_edge = edge - required

                category = self._category(source, target, held_assets, leader_asset, holdings, prices)



                base_pct = self.expansion_size_pct if is_expansion else self.trade_size_pct

                if src_heavy:

                    base_pct = min(base_pct * 1.25, 0.25)

                size_pct = self._viable_size_pct(source, holdings, prices, base_pct)

                if size_pct <= 0:

                    continue



                is_defensive = src_score <= self.momentum_sell and not is_held_swap

                require_leader_stable = (

                    target == leader_asset

                    and leader_asset not in held_assets

                    and not is_defensive

                    and category != "diversify"

                )



                tgt_alloc = self._allocation_pct(target, holdings, prices)

                reason = self._build_reason(

                    source, target, src_score, tgt_score, edge, path, hops, category, is_defensive, tgt_alloc

                )



                candidate = _RotationCandidate(

                    from_asset=source,

                    to_asset=target,

                    edge=edge,

                    required=required,

                    net_edge=net_edge,

                    diversify_score=0.0,

                    hops=hops,

                    path=path,

                    category=category,

                    size_pct=size_pct,

                    is_defensive=is_defensive,

                    is_held_swap=is_held_swap,

                    is_expansion=is_expansion,

                    require_leader_stable=require_leader_stable,

                    reason=reason,

                )

                candidate.diversify_score = self._diversify_score(candidate, holdings, prices)

                candidates.append(candidate)



        return candidates



    def _candidate_to_option(self, c: _RotationCandidate) -> RotationOption:

        return RotationOption(

            from_asset=c.from_asset,

            to_asset=c.to_asset,

            edge=c.edge,

            required_edge=c.required,

            category=c.category,

            path=c.path,

            hops=c.hops,

        )



    def _candidate_to_intent(self, c: _RotationCandidate) -> TradeIntent:

        return TradeIntent(

            from_asset=c.from_asset,

            to_asset=c.to_asset,

            reason=c.reason,

            size_pct=c.size_pct,

            edge=c.edge,

            is_defensive=c.is_defensive,

            is_held_swap=c.is_held_swap,

            is_expansion=c.is_expansion,

            require_leader_stable=c.require_leader_stable,

        )



    def evaluate(

        self,

        candles: dict[str, pd.DataFrame],

        prices: dict[str, float],

        holdings: dict[str, float],

        risk: RiskManager | None = None,

        markets: "MarketRegistry | None" = None,

        context=None,

    ) -> StrategyResult:

        scores = {symbol: self._momentum_score(candles[symbol]) for symbol in self.usd_symbols}

        signals = {symbol: Signal.HOLD for symbol in self.usd_symbols}

        reasons: dict[str, str] = {}

        sizes: dict[str, float] = {}

        intents: list[TradeIntent] = []

        blocked: list[str] = []

        opportunities: list[RotationOption] = []



        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)

        leader_symbol, leader_score = ranked[0]

        leader_asset = self.symbol_assets[leader_symbol]

        ranked_assets = self._ranked_assets(scores)

        usd = holdings.get("USD", 0.0)

        held_assets = self._held_assets(holdings)



        if risk:

            risk.update_leader(leader_symbol)



        if risk and risk.is_paused():

            return StrategyResult(

                signals=signals, scores=scores, reasons=reasons, sizes=sizes,

                intents=[], leader=None, idle_reason=risk.pause_status(),

            )



        for asset in held_assets:

            score = self._asset_score(asset, scores)

            if score > self.momentum_sell:

                continue

            value = self._position_usd(asset, holdings, prices)

            size = 1.0 if value < self.dust_usd and asset not in self.core_assets else self.trade_size_pct

            intents.append(

                TradeIntent(

                    from_asset=asset,

                    to_asset="USD",

                    reason=f"mitigating losses - {asset} momentum turned negative ({score:+.4f})",

                    size_pct=size,

                    edge=abs(score),

                    is_defensive=True,

                    is_held_swap=False,

                )

            )

            sym = self.asset_usd_symbols[asset]

            signals[sym] = Signal.SELL

            reasons[sym] = "Defensive exit"



        if not intents and held_assets:

            candidates = self._scan_rotations(

                held_assets, holdings, prices, scores, leader_asset, risk, markets

            )

            ranked_candidates = sorted(
                candidates,
                key=lambda c: (
                    -c.diversify_score,
                    funding_rank(c.from_asset, self.preferred_start_assets),
                ),
            )



            by_source: dict[str, list[_RotationCandidate]] = {a: [] for a in held_assets}

            for c in ranked_candidates:

                by_source[c.from_asset].append(c)

            for source in held_assets:

                opportunities.extend(

                    self._candidate_to_option(c) for c in by_source[source][:4]

                )



            viable = [c for c in ranked_candidates if c.diversify_score >= 0 or c.is_defensive]

            best_near = ranked_candidates[0] if ranked_candidates else None



            if viable:

                best = viable[0]

                if best.require_leader_stable and risk and not risk.leader_is_stable():

                    blocked.append(

                        f"Best move {best.from_asset} -> {best.to_asset} waiting on leader stability "

                        f"({risk.leader_stable_for()}s / {risk.effective_leader_stable_seconds()}s)"

                    )

                else:

                    intents.append(self._candidate_to_intent(best))

            elif best_near:

                path_note = f" via {best_near.path.replace('->', ' -> ')}" if best_near.path else ""

                blocked.append(

                    f"Best {best_near.category}: {best_near.from_asset} -> {best_near.to_asset}{path_note} "

                    f"(edge {best_near.edge:+.4f}, need {best_near.required:+.4f} to cover fees)"

                )



        if not intents and usd > 0:

            best_usd: _RotationCandidate | None = None

            for target in ranked_assets:

                tgt_score = self._asset_score(target, scores)

                route_info = self._route_requirements("USD", target, held_assets, risk, markets)

                if not route_info:

                    continue

                hops, required, path = route_info

                edge = tgt_score

                net_edge = edge - required

                size_pct = self._viable_size_pct("USD", holdings, prices, self.expansion_size_pct)

                if size_pct <= 0:

                    continue

                category = "leader_rotation" if target == leader_asset else "expansion"

                path_note = f" via {path.replace('->', ' -> ')}" if path and hops > 1 else ""

                candidate = _RotationCandidate(

                    from_asset="USD",

                    to_asset=target,

                    edge=edge,

                    required=required,

                    net_edge=net_edge,

                    diversify_score=net_edge + self.diversify_bonus,

                    hops=hops,

                    path=path,

                    category=category,

                    size_pct=size_pct,

                    is_defensive=False,

                    is_held_swap=False,

                    is_expansion=True,

                    require_leader_stable=(target == leader_asset),

                    reason=(

                        f"diversifying - buying {target} with USD "

                        f"(momentum {tgt_score:+.4f}){path_note}"

                    ),

                )

                tgt_alloc = self._allocation_pct(target, holdings, prices)

                avg_weight = self._average_weight(holdings)

                if tgt_alloc < avg_weight:

                    candidate.diversify_score += self.diversify_bonus

                opportunities.append(self._candidate_to_option(candidate))

                if best_usd is None or candidate.diversify_score > best_usd.diversify_score:

                    best_usd = candidate



            if best_usd and best_usd.diversify_score >= 0:

                if best_usd.require_leader_stable and risk and not risk.leader_is_stable():

                    blocked.append(

                        f"Would buy {best_usd.to_asset} with USD but leader not stable yet"

                    )

                else:

                    intents.append(self._candidate_to_intent(best_usd))

            elif best_usd:

                blocked.append(

                    f"Best USD buy: {best_usd.to_asset} "

                    f"(edge {best_usd.edge:+.4f}, need {best_usd.required:+.4f} to cover fees)"

                )



        idle_reason = self._idle_reason(

            leader_asset=leader_asset,

            leader_score=leader_score,

            intents=intents,

            held_assets=held_assets,

            risk=risk,

            blocked=blocked,

        )



        return StrategyResult(

            signals=signals, scores=scores, reasons=reasons, sizes=sizes,

            intents=intents, leader=leader_symbol if intents else None,

            idle_reason=idle_reason, blocked=blocked, opportunities=opportunities,

        )



    def _idle_reason(

        self,

        leader_asset: str,

        leader_score: float,

        intents: list[TradeIntent],

        held_assets: list[str],

        risk: RiskManager | None,

        blocked: list[str],

    ) -> str:

        if intents:

            return ""



        if blocked:

            return blocked[0]



        if risk and risk.cooldown_remaining() > 0:

            return f"Waiting - cooldown {risk.cooldown_remaining()}s between trades"



        if held_assets:

            return (

                f"Holding {len(held_assets)} coins across {len(self.watch_assets)} watchlist assets - "

                f"scanning for fee-justified spread (leader: {leader_asset} {leader_score:+.4f})"

            )



        return "Waiting for a clear opportunity"


