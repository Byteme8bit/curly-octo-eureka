"""Real-money execution on Kraken via ccxt market orders."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import ccxt

from bot.equities import is_equity_asset
from bot.live_guards import LIVE_SYNC_ASSETS, build_live_sync_assets, check_live_route
from bot.markets import PairInfo, RouteLeg, TradeRoute
from bot.paper_broker import PaperBroker, PaperState, RiskState
from bot.strategies.base import Signal

logger = logging.getLogger(__name__)


class LiveBroker:
    """Execute multi-leg routes on Kraken; mirrors PaperBroker's surface for the engine."""

    def __init__(
        self,
        exchange: ccxt.kraken,
        fee_rate: float,
        state_file: Path,
        min_usd_trade: float = 5.0,
        max_usd_per_trade: float = 100.0,
        max_usd_per_route: float = 100.0,
        allowed_assets: tuple[str, ...] = ("ETH", "ADA"),
        allow_triangular: bool = False,
        max_route_legs: int = 1,
        reset: bool = False,
        equity_assets: frozenset[str] | None = None,
        sync_assets: frozenset[str] | None = None,
    ):
        self.exchange = exchange
        self.fee_rate = fee_rate
        self.min_usd_trade = min_usd_trade
        self.max_usd_per_trade = max_usd_per_trade
        self.max_usd_per_route = max_usd_per_route
        self.allowed_assets = allowed_assets
        self.equity_assets = equity_assets or frozenset()
        self.sync_assets = sync_assets or build_live_sync_assets(
            allowed_assets, self.equity_assets
        )
        self.allow_triangular = allow_triangular
        self.max_route_legs = max_route_legs
        self.state_file = state_file
        self.halted = False
        self.halt_reason = ""
        self.state = self._load_or_create(reset)
        self.sync_from_exchange()

    def _route_guard_kwargs(self) -> dict:
        return {
            "allow_triangular": self.allow_triangular,
            "max_route_legs": self.max_route_legs,
        }

    def _load_or_create(self, reset: bool) -> PaperState:
        if reset and self.state_file.exists():
            self.state_file.unlink()
        if self.state_file.exists():
            with open(self.state_file, encoding="utf-8") as f:
                return PaperState.from_dict(json.load(f))
        return PaperState(balances={}, cost_basis={})

    def save(self) -> None:
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.state.to_dict(), f, indent=2)

    def reset_state(self) -> None:
        """Re-anchor risk tracking from current exchange balances."""
        if self.state_file.exists():
            self.state_file.unlink()
        self.state = PaperState(balances={}, cost_basis={})
        self.halted = False
        self.halt_reason = ""
        self.sync_from_exchange()
        self.save()

    def halt(self, reason: str) -> None:
        self.halted = True
        self.halt_reason = reason
        logger.error("LIVE HALT: %s", reason)

    def record_completed_trade(self) -> int:
        """Increment persisted live trade counter; return new count."""
        self.state.risk.live_trades_completed += 1
        self.save()
        return self.state.risk.live_trades_completed

    @property
    def risk(self) -> RiskState:
        return self.state.risk

    def balance(self, asset: str) -> float:
        return self.state.balances.get(asset, 0.0)

    def _asset_usd(self, asset: str, usd_prices: dict[str, float]) -> float:
        if asset == "USD":
            return 1.0
        return usd_prices.get(asset, 0.0)

    def sync_from_exchange(self) -> None:
        """Refresh local balances from Kraken."""
        try:
            raw = self.exchange.fetch_balance()
        except ccxt.BaseError as exc:
            logger.warning("Live balance sync failed: %s", exc)
            return
        totals = raw.get("total") or {}
        for asset, qty in totals.items():
            if asset not in self.sync_assets:
                continue
            if qty and float(qty) > 0:
                self.state.balances[asset] = float(qty)
            elif asset in self.state.balances:
                self.state.balances[asset] = 0.0
        self.save()

    def ensure_cost_basis(self, usd_prices: dict[str, float]) -> None:
        updated = False
        for asset, qty in self.state.balances.items():
            if asset == "USD" or qty <= 0:
                continue
            if self.state.cost_basis.get(asset, 0.0) <= 0:
                price = self._asset_usd(asset, usd_prices)
                if price > 0:
                    self.state.cost_basis[asset] = qty * price
                    updated = True
        if updated:
            self.save()

    def portfolio_value(self, usd_prices: dict[str, float]) -> float:
        total = self.balance("USD")
        for asset, qty in self.state.balances.items():
            if asset == "USD" or qty <= 0:
                continue
            total += qty * self._asset_usd(asset, usd_prices)
        return total

    def execute(
        self,
        pair: PairInfo,
        side: Signal,
        price: float,
        usd_prices: dict[str, float],
        reason: str = "",
        size_pct: float = 1.0,
        *,
        record: bool = True,
    ) -> dict | None:
        trade = self._execute_leg(pair, side, price, usd_prices, reason, size_pct)
        if trade and record:
            self.state.trades.append(trade)
            self.save()
        return trade

    def _estimate_leg_usd(
        self,
        leg: RouteLeg,
        size_pct: float,
        price: float,
        usd_prices: dict[str, float],
        *,
        from_qty_override: float | None = None,
    ) -> float:
        if leg.side == Signal.BUY:
            quote_bal = (
                from_qty_override
                if from_qty_override is not None
                else self.balance(leg.from_asset)
            )
            quote_spend = quote_bal * size_pct
            return quote_spend * self._asset_usd(leg.from_asset, usd_prices)
        base_bal = (
            from_qty_override
            if from_qty_override is not None
            else self.balance(leg.from_asset)
        )
        base_qty = base_bal * size_pct
        return base_qty * self._asset_usd(leg.from_asset, usd_prices)

    def _simulate_leg(
        self,
        leg: RouteLeg,
        *,
        size_pct: float,
        price: float,
        usd_prices: dict[str, float],
        available_from: float,
        apply_usd_cap: bool,
    ) -> tuple[float, float, float, str]:
        """
        Return (from_qty, to_qty, trade_usd, error_reason).
        error_reason empty when the leg can fund.
        """
        if price <= 0 or available_from <= 0 or size_pct <= 0:
            return 0.0, 0.0, 0.0, f"Leg cannot fund {leg.from_asset}"

        base = leg.pair.base
        quote = leg.pair.quote

        if leg.side == Signal.BUY:
            quote_spend = available_from * size_pct
            trade_usd = quote_spend * self._asset_usd(quote, usd_prices)
            if apply_usd_cap:
                capped = self._cap_size_pct(trade_usd, size_pct)
                quote_spend = available_from * capped
                trade_usd = quote_spend * self._asset_usd(quote, usd_prices)
            if trade_usd < self.min_usd_trade:
                return (
                    0.0,
                    0.0,
                    trade_usd,
                    f"Leg {leg.pair.symbol} trade ${trade_usd:.2f} below min ${self.min_usd_trade:.2f}",
                )
            to_qty = (quote_spend * (1.0 - self.fee_rate)) / price
            return quote_spend, to_qty, trade_usd, ""

        base_qty = available_from * size_pct
        trade_usd = base_qty * self._asset_usd(base, usd_prices)
        if apply_usd_cap:
            capped = self._cap_size_pct(trade_usd, size_pct)
            base_qty = available_from * capped
            trade_usd = base_qty * self._asset_usd(base, usd_prices)
        if base_qty <= 0 or trade_usd < self.min_usd_trade:
            return (
                0.0,
                0.0,
                trade_usd,
                f"Leg {leg.pair.symbol} trade ${trade_usd:.2f} below min ${self.min_usd_trade:.2f}",
            )
        to_qty = base_qty * price * (1.0 - self.fee_rate)
        return base_qty, to_qty, trade_usd, ""

    def _preflight_route(
        self,
        route: TradeRoute,
        prices: dict[str, float],
        usd_prices: dict[str, float],
        size_pct: float,
    ) -> tuple[bool, str]:
        """Simulate sequential funding across all legs before placing orders."""
        if not route.legs:
            return False, "Empty route"
        wallet = {k: float(v) for k, v in self.state.balances.items()}
        route_produced: dict[str, float] = {}

        for index, leg in enumerate(route.legs):
            price = prices.get(leg.pair.symbol, 0.0)
            if price <= 0:
                return False, f"Leg {index + 1}/{route.hops} missing price for {leg.pair.symbol}"

            leg_pct = size_pct if index == 0 else 1.0
            from_asset = leg.from_asset
            wallet_bal = wallet.get(from_asset, 0.0)
            produced = route_produced.get(from_asset, 0.0)
            if index == 0:
                available = wallet_bal
            else:
                # Later legs spend only what this route produced on the prior leg.
                available = min(produced, wallet_bal) if produced > 0 else wallet_bal

            if available <= 0:
                return (
                    False,
                    f"Leg {index + 1}/{route.hops} insufficient {from_asset} "
                    f"(need prior leg output; wallet={wallet_bal:.8f})",
                )

            from_qty, to_qty, trade_usd, err = self._simulate_leg(
                leg,
                size_pct=leg_pct,
                price=price,
                usd_prices=usd_prices,
                available_from=available,
                apply_usd_cap=index == 0,
            )
            if err:
                return False, f"Leg {index + 1}/{route.hops} {leg.pair.symbol}: {err}"

            market = self.exchange.market(leg.pair.symbol)
            min_amt = (market.get("limits") or {}).get("amount", {}).get("min")
            out_asset = leg.to_asset
            out_qty = to_qty if leg.side == Signal.BUY else to_qty
            spend_qty = from_qty
            check_qty = spend_qty if leg.side == Signal.SELL else to_qty
            if min_amt and check_qty < float(min_amt):
                return (
                    False,
                    f"Leg {index + 1}/{route.hops} {leg.pair.symbol}: "
                    f"qty {check_qty:.8f} below exchange min {min_amt}",
                )

            wallet[from_asset] = max(0.0, wallet_bal - spend_qty)
            route_produced = {out_asset: out_qty}
            wallet[out_asset] = wallet.get(out_asset, 0.0) + out_qty

        return True, ""

    def _cap_route_size_pct(
        self,
        route: TradeRoute,
        prices: dict[str, float],
        usd_prices: dict[str, float],
        size_pct: float,
    ) -> float:
        if not route.legs or self.max_usd_per_route <= 0:
            return size_pct
        first = route.legs[0]
        price = prices.get(first.pair.symbol, 0.0)
        if price <= 0:
            return size_pct
        est_usd = self._estimate_leg_usd(first, size_pct, price, usd_prices)
        if est_usd <= self.max_usd_per_route:
            return size_pct
        return size_pct * (self.max_usd_per_route / est_usd)

    def execute_path(
        self,
        route: TradeRoute,
        prices: dict[str, float],
        usd_prices: dict[str, float],
        reason: str = "",
        size_pct: float = 1.0,
        *,
        strategy_name: str = "",
    ) -> dict | None:
        if self.halted:
            return None
        if not route.legs:
            return None
        allowed, block_reason = check_live_route(
            route,
            self.allowed_assets,
            **self._route_guard_kwargs(),
        )
        if not allowed:
            logger.warning("Live path blocked: %s", block_reason)
            return None

        self.sync_from_exchange()
        size_pct = self._cap_route_size_pct(route, prices, usd_prices, size_pct)
        ok, preflight_reason = self._preflight_route(route, prices, usd_prices, size_pct)
        if not ok:
            logger.warning("Live path preflight blocked: %s (%s)", preflight_reason, route.path)
            return None

        leg_trades: list[dict] = []
        route_produced: dict[str, float] = {}
        for index, leg in enumerate(route.legs):
            price = prices.get(leg.pair.symbol, 0.0)
            leg_size = size_pct if index == 0 else 1.0
            from_asset = leg.from_asset
            wallet_bal = self.balance(from_asset)
            produced = route_produced.get(from_asset, 0.0)
            if index == 0:
                max_from = None
            else:
                cap = min(produced, wallet_bal) if produced > 0 else wallet_bal
                max_from = cap if cap > 0 else None
            try:
                trade = self._execute_leg(
                    leg.pair,
                    leg.side,
                    price,
                    usd_prices,
                    reason=f"{reason} (leg {index + 1}/{route.hops})",
                    size_pct=leg_size,
                    apply_usd_cap=index == 0,
                    max_from_qty=max_from,
                )
            except ccxt.BaseError as exc:
                msg = (
                    f"Live leg {index + 1}/{route.hops} failed on {leg.pair.symbol}: {exc}"
                )
                if leg_trades:
                    rollback_ok = self._rollback_legs(
                        leg_trades, prices, usd_prices, path_reason=reason
                    )
                    if not rollback_ok:
                        msg += f" — rollback failed after {len(leg_trades)} leg(s)"
                self.halt(msg)
                return None
            if not trade:
                if index > 0:
                    rollback_ok = self._rollback_legs(
                        leg_trades, prices, usd_prices, path_reason=reason
                    )
                    msg = (
                        f"Live path stalled after leg {index}/{route.hops} — "
                        f"holdings may be mid-route ({route.path})"
                    )
                    if rollback_ok:
                        msg += " — rolled back completed legs"
                        logger.warning(msg)
                    else:
                        msg += " — rollback failed"
                        self.halt(msg)
                else:
                    logger.warning(
                        "Live path leg 1 returned None on %s (%s)",
                        leg.pair.symbol,
                        route.path,
                    )
                return None
            leg_trades.append(trade)
            if leg.side == Signal.BUY:
                route_produced = {leg.to_asset: float(trade.get("to_qty", 0.0))}
            else:
                route_produced = {leg.to_asset: float(trade.get("to_qty", 0.0))}

        combined = PaperBroker._combine_path_trade(
            None,
            route,
            leg_trades,
            reason,
            size_pct,
            strategy_name=strategy_name,
        )
        combined["live"] = True
        self.state.trades.append(combined)
        self.save()
        return combined

    def _rollback_legs(
        self,
        leg_trades: list[dict],
        prices: dict[str, float],
        usd_prices: dict[str, float],
        *,
        path_reason: str,
    ) -> bool:
        """Best-effort reverse of completed legs (newest first). Returns True if all reversed."""
        ok = True
        for trade in reversed(leg_trades):
            pair, reverse_side = self._reverse_leg(trade)
            price = prices.get(pair.symbol, trade.get("price", 0.0))
            try:
                undone = self._execute_leg(
                    pair,
                    reverse_side,
                    price,
                    usd_prices,
                    reason=f"[rollback] {path_reason}",
                    size_pct=1.0,
                    skip_route_check=True,
                )
            except ccxt.BaseError as exc:
                logger.error("Live rollback leg failed on %s: %s", pair.symbol, exc)
                ok = False
                continue
            if not undone:
                logger.error("Live rollback leg returned None on %s", pair.symbol)
                ok = False
        return ok

    @staticmethod
    def _reverse_leg(trade: dict) -> tuple[PairInfo, Signal]:
        symbol = trade["symbol"]
        if trade["side"] == "buy":
            pair = PairInfo(
                symbol=symbol,
                base=trade["to_asset"],
                quote=trade["from_asset"],
            )
            return pair, Signal.SELL
        pair = PairInfo(
            symbol=symbol,
            base=trade["from_asset"],
            quote=trade["to_asset"],
        )
        return pair, Signal.BUY

    def _cap_size_pct(self, trade_usd: float, size_pct: float) -> float:
        if trade_usd <= 0 or self.max_usd_per_trade <= 0:
            return size_pct
        if trade_usd <= self.max_usd_per_trade:
            return size_pct
        return size_pct * (self.max_usd_per_trade / trade_usd)

    def _execute_leg(
        self,
        pair: PairInfo,
        side: Signal,
        price: float,
        usd_prices: dict[str, float],
        reason: str = "",
        size_pct: float = 1.0,
        *,
        skip_route_check: bool = False,
        apply_usd_cap: bool = True,
        max_from_qty: float | None = None,
    ) -> dict | None:
        if self.halted or side == Signal.HOLD:
            return None

        if not skip_route_check:
            single_leg = TradeRoute(
                legs=(
                    RouteLeg(
                        pair=pair,
                        side=side,
                        from_asset=pair.quote if side == Signal.BUY else pair.base,
                        to_asset=pair.base if side == Signal.BUY else pair.quote,
                    ),
                )
            )
            allowed, block_reason = check_live_route(
                single_leg,
                self.allowed_assets,
                **self._route_guard_kwargs(),
            )
            if not allowed:
                logger.warning("Live leg blocked: %s", block_reason)
                return None

        size_pct = max(0.0, min(1.0, size_pct))
        if size_pct <= 0 or price <= 0:
            return None

        base = pair.base
        quote = pair.quote
        symbol = pair.symbol

        if side == Signal.BUY:
            quote_bal = self.balance(quote)
            if max_from_qty is not None:
                quote_bal = min(quote_bal, max_from_qty)
            quote_spend = quote_bal * size_pct
            quote_usd = self._asset_usd(quote, usd_prices)
            trade_usd = quote_spend * quote_usd
            if apply_usd_cap:
                size_pct = self._cap_size_pct(trade_usd, size_pct)
                quote_spend = quote_bal * size_pct
                trade_usd = quote_spend * quote_usd
            if trade_usd < self.min_usd_trade:
                return None
            base_qty = (quote_spend * (1.0 - self.fee_rate)) / price
        else:
            base_bal = self.balance(base)
            if max_from_qty is not None:
                base_bal = min(base_bal, max_from_qty)
            base_qty = base_bal * size_pct
            base_usd = self._asset_usd(base, usd_prices)
            trade_usd = base_qty * base_usd
            if apply_usd_cap:
                size_pct = self._cap_size_pct(trade_usd, size_pct)
                base_qty = base_bal * size_pct
                trade_usd = base_qty * base_usd
            if base_qty <= 0 or trade_usd < self.min_usd_trade:
                return None

        amount = float(self.exchange.amount_to_precision(symbol, base_qty))
        market = self.exchange.market(symbol)
        min_amt = (market.get("limits") or {}).get("amount", {}).get("min")
        if min_amt and amount < float(min_amt):
            return None

        side_str = "buy" if side == Signal.BUY else "sell"
        params: dict = {}
        if is_equity_asset(base, self.equity_assets):
            params["asset_class"] = "tokenized_asset"
        if params:
            order = self.exchange.create_order(
                symbol, "market", side_str, amount, params=params
            )
        else:
            order = self.exchange.create_order(symbol, "market", side_str, amount)
        order_id = order.get("id")
        if order_id and order.get("status") != "closed":
            order = self.exchange.fetch_order(order_id, symbol)

        filled = float(order.get("filled") or amount)
        avg_price = float(order.get("average") or order.get("price") or price)
        fee_cost = 0.0
        fee_currency = quote
        for fee in order.get("fees") or []:
            fee_cost += float(fee.get("cost") or 0.0)
            if fee.get("currency"):
                fee_currency = fee["currency"]
        if fee_cost <= 0 and order.get("fee"):
            fee_cost = float(order["fee"].get("cost") or 0.0)
            fee_currency = order["fee"].get("currency") or fee_currency

        self.sync_from_exchange()
        now = datetime.now(timezone.utc).isoformat()
        fee_usd = fee_cost * self._asset_usd(fee_currency, usd_prices)

        if side == Signal.BUY:
            quote_spend = filled * avg_price
            trade_type = "cross" if quote != "USD" else "usd"
            cost_usd = quote_spend * self._asset_usd(quote, usd_prices)
            self.state.cost_basis[base] = self.state.cost_basis.get(base, 0.0) + cost_usd
            gain_loss = -fee_usd if trade_type == "usd" else -fee_usd
            trade = {
                "time": now,
                "symbol": symbol,
                "side": "buy",
                "type": trade_type,
                "from_asset": quote,
                "to_asset": base,
                "from_qty": quote_spend,
                "to_qty": filled,
                "price": avg_price,
                "base_qty": filled,
                "quote_qty": quote_spend,
                "qty": filled,
                "size_pct": size_pct,
                "fee_quote": fee_cost,
                "fee_usd": fee_usd,
                "reason": reason,
                "gain_loss": gain_loss,
                "order_id": order_id,
                "live": True,
            }
        else:
            gross_quote = filled * avg_price
            net_quote = gross_quote - fee_cost
            quote_usd = self._asset_usd(quote, usd_prices)
            base_bal_before = self.balance(base) + filled
            total_cost = self.state.cost_basis.get(base, 0.0)
            cost_of_sold = total_cost * (filled / base_bal_before) if base_bal_before > 0 else 0.0
            gain_loss = (net_quote * quote_usd) - cost_of_sold
            self.state.cost_basis[base] = max(0.0, total_cost - cost_of_sold)
            trade = {
                "time": now,
                "symbol": symbol,
                "side": "sell",
                "type": "cross" if quote != "USD" else "usd",
                "from_asset": base,
                "to_asset": quote,
                "from_qty": filled,
                "to_qty": net_quote,
                "price": avg_price,
                "base_qty": filled,
                "quote_qty": net_quote,
                "qty": filled,
                "size_pct": size_pct,
                "fee_quote": fee_cost,
                "fee_usd": fee_usd,
                "reason": reason,
                "gain_loss": gain_loss,
                "order_id": order_id,
                "live": True,
            }

        return trade
