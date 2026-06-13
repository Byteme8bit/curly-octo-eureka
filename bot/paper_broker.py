import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from bot.markets import PairInfo, TradeRoute
from bot.strategies.base import Signal


@dataclass
class RiskState:
    peak_portfolio: float = 0.0
    baseline_portfolio: float = 0.0
    paused_until: str | None = None
    hibernate_alert_sent: bool = False
    last_trade_at: str | None = None
    leader_symbol: str | None = None
    leader_since: str | None = None
    trades_this_hour: int = 0
    hour_window_start: str | None = None
    reevaluation_mode: bool = False
    circuit_breaker_at: str | None = None
    session_started_at: str | None = None
    adaptive_alert_sent: bool = False
    adaptive_relax_attempts: int = 0
    adaptive_suspended: bool = False
    adaptive_suspended_at: str | None = None
    dominant_strategy: str | None = None
    dominant_since: str | None = None
    growth_window_start_at: str | None = None
    growth_window_start_value: float = 0.0
    strategy_stats: dict = field(default_factory=dict)
    total_trades: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "RiskState":
        if not data:
            return cls()
        return cls(
            peak_portfolio=float(data.get("peak_portfolio", 0.0)),
            baseline_portfolio=float(data.get("baseline_portfolio", 0.0)),
            paused_until=data.get("paused_until"),
            hibernate_alert_sent=bool(data.get("hibernate_alert_sent", False)),
            last_trade_at=data.get("last_trade_at"),
            leader_symbol=data.get("leader_symbol"),
            leader_since=data.get("leader_since"),
            trades_this_hour=int(data.get("trades_this_hour", 0)),
            hour_window_start=data.get("hour_window_start"),
            reevaluation_mode=bool(data.get("reevaluation_mode", False)),
            circuit_breaker_at=data.get("circuit_breaker_at"),
            session_started_at=data.get("session_started_at"),
            adaptive_alert_sent=bool(data.get("adaptive_alert_sent", False)),
            adaptive_relax_attempts=int(data.get("adaptive_relax_attempts", 0)),
            adaptive_suspended=bool(data.get("adaptive_suspended", False)),
            adaptive_suspended_at=data.get("adaptive_suspended_at"),
            dominant_strategy=data.get("dominant_strategy"),
            dominant_since=data.get("dominant_since"),
            growth_window_start_at=data.get("growth_window_start_at"),
            growth_window_start_value=float(data.get("growth_window_start_value", 0.0)),
            strategy_stats=dict(data.get("strategy_stats") or {}),
            total_trades=int(data.get("total_trades", 0)),
        )


@dataclass
class PaperState:
    balances: dict[str, float]
    cost_basis: dict[str, float]
    trades: list[dict] = field(default_factory=list)
    risk: RiskState = field(default_factory=RiskState)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["risk"] = self.risk.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "PaperState":
        if "balances" in data:
            balances = {k: float(v) for k, v in data["balances"].items()}
            cost_basis = {k: float(v) for k, v in data.get("cost_basis", {}).items()}
            return cls(
                balances=balances,
                cost_basis=cost_basis,
                trades=list(data.get("trades", [])),
                risk=RiskState.from_dict(data.get("risk")),
            )

        balances = {
            "USD": float(data.get("usd", 0.0)),
            "ETH": float(data.get("eth", 0.0)),
            "ADA": 0.0,
        }
        return cls(balances=balances, cost_basis={}, trades=list(data.get("trades", [])), risk=RiskState())


class PaperBroker:
    def __init__(
        self,
        initial_balances: dict[str, float],
        fee_rate: float,
        state_file: Path,
        min_usd_trade: float = 5.0,
        reset: bool = False,
    ):
        self.fee_rate = fee_rate
        self.min_usd_trade = min_usd_trade
        self.state_file = state_file
        self.initial_balances = dict(initial_balances)
        self.state = self._load_or_create(reset)

    def _load_or_create(self, reset: bool) -> PaperState:
        if reset and self.state_file.exists():
            self.state_file.unlink()

        if self.state_file.exists():
            with open(self.state_file, encoding="utf-8") as f:
                return PaperState.from_dict(json.load(f))

        return PaperState(balances=dict(self.initial_balances), cost_basis={})

    def save(self) -> None:
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.state.to_dict(), f, indent=2)

    def reset_state(self) -> None:
        if self.state_file.exists():
            self.state_file.unlink()
        self.state = PaperState(balances=dict(self.initial_balances), cost_basis={})
        self.save()

    @property
    def risk(self) -> RiskState:
        return self.state.risk

    def balance(self, asset: str) -> float:
        return self.state.balances.get(asset, 0.0)

    def _asset_usd(self, asset: str, usd_prices: dict[str, float]) -> float:
        if asset == "USD":
            return 1.0
        return usd_prices.get(asset, 0.0)

    def ensure_cost_basis(self, usd_prices: dict[str, float]) -> None:
        updated = False
        for asset, qty in self.state.balances.items():
            if asset in ("USD",) or qty <= 0:
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
        if not route.legs:
            return None

        leg_trades: list[dict] = []
        for index, leg in enumerate(route.legs):
            price = prices.get(leg.pair.symbol, 0.0)
            leg_size = size_pct if index == 0 else 1.0
            trade = self._execute_leg(
                leg.pair,
                leg.side,
                price,
                usd_prices,
                reason=f"{reason} (leg {index + 1}/{route.hops})",
                size_pct=leg_size,
            )
            if not trade:
                return None
            leg_trades.append(trade)

        combined = self._combine_path_trade(
            route, leg_trades, reason, size_pct, strategy_name=strategy_name
        )
        self.state.trades.append(combined)
        self.save()
        return combined

    def _combine_path_trade(
        self,
        route: TradeRoute,
        leg_trades: list[dict],
        reason: str,
        size_pct: float,
        *,
        strategy_name: str = "",
    ) -> dict:
        first = leg_trades[0]
        last = leg_trades[-1]
        multi = route.hops > 1
        return {
            "time": first["time"],
            "symbol": route.symbols[-1] if multi else first["symbol"],
            "side": "buy" if last["side"] == "buy" else "sell",
            "type": "multi_hop" if multi else first["type"],
            "from_asset": first["from_asset"],
            "to_asset": last["to_asset"],
            "from_qty": first["from_qty"],
            "to_qty": last["to_qty"],
            "price": last["price"],
            "base_qty": last["base_qty"],
            "quote_qty": last["quote_qty"],
            "qty": last["qty"],
            "size_pct": size_pct,
            "fee_quote": sum(t.get("fee_quote", 0.0) for t in leg_trades),
            "fee_usd": sum(t.get("fee_usd", 0.0) for t in leg_trades),
            "reason": reason,
            "gain_loss": sum(t.get("gain_loss", 0.0) for t in leg_trades),
            "path": route.path,
            "hops": route.hops,
            "legs": leg_trades,
            "strategy_name": strategy_name,
        }

    def _execute_leg(
        self,
        pair: PairInfo,
        side: Signal,
        price: float,
        usd_prices: dict[str, float],
        reason: str = "",
        size_pct: float = 1.0,
    ) -> dict | None:
        if side == Signal.HOLD:
            return None

        size_pct = max(0.0, min(1.0, size_pct))
        if size_pct <= 0 or price <= 0:
            return None

        now = datetime.now(timezone.utc).isoformat()
        base = pair.base
        quote = pair.quote

        if side == Signal.BUY:
            quote_bal = self.balance(quote)
            quote_spend = quote_bal * size_pct
            quote_usd = self._asset_usd(quote, usd_prices)
            trade_usd = quote_spend * quote_usd
            if trade_usd < self.min_usd_trade:
                return None
            fee_quote = quote_spend * self.fee_rate
            net_quote = quote_spend - fee_quote
            base_qty = net_quote / price
            self.state.balances[quote] = quote_bal - quote_spend
            self.state.balances[base] = self.balance(base) + base_qty
            cost_usd = net_quote * quote_usd
            self.state.cost_basis[base] = self.state.cost_basis.get(base, 0.0) + cost_usd
            trade_type = "cross" if quote != "USD" else "usd"
            if trade_type == "cross":
                from_usd = quote_spend * quote_usd
                base_usd = self._asset_usd(base, usd_prices)
                if base_usd > 0:
                    to_usd = base_qty * base_usd
                else:
                    # No USD reference for the asset we just bought (common when
                    # diversifying into a coin we did not previously hold). Value
                    # it from the post-fee quote we converted so a conversion's
                    # immediate P&L is just the fee paid, not a phantom loss of
                    # the whole notional.
                    to_usd = net_quote * quote_usd
                gain_loss = to_usd - from_usd
            else:
                gain_loss = 0.0
            trade = {
                "time": now,
                "symbol": pair.symbol,
                "side": "buy",
                "type": trade_type,
                "from_asset": quote,
                "to_asset": base,
                "from_qty": quote_spend,
                "to_qty": base_qty,
                "price": price,
                "base_qty": base_qty,
                "quote_qty": quote_spend,
                "qty": base_qty,
                "size_pct": size_pct,
                "fee_quote": fee_quote,
                "fee_usd": fee_quote * quote_usd,
                "reason": reason,
                "gain_loss": gain_loss,
            }

        elif side == Signal.SELL:
            base_bal = self.balance(base)
            base_qty = base_bal * size_pct
            base_usd = self._asset_usd(base, usd_prices)
            trade_usd = base_qty * base_usd
            if base_qty <= 0 or trade_usd < self.min_usd_trade:
                return None
            gross_quote = base_qty * price
            fee_quote = gross_quote * self.fee_rate
            net_quote = gross_quote - fee_quote
            quote_usd = self._asset_usd(quote, usd_prices)
            total_cost = self.state.cost_basis.get(base, 0.0)
            cost_of_sold = total_cost * (base_qty / base_bal) if base_bal > 0 else 0.0
            gain_loss = (net_quote * quote_usd) - cost_of_sold
            self.state.balances[base] = base_bal - base_qty
            self.state.balances[quote] = self.balance(quote) + net_quote
            self.state.cost_basis[base] = max(0.0, total_cost - cost_of_sold)
            trade = {
                "time": now,
                "symbol": pair.symbol,
                "side": "sell",
                "type": "cross" if quote != "USD" else "usd",
                "from_asset": base,
                "to_asset": quote,
                "from_qty": base_qty,
                "to_qty": net_quote,
                "price": price,
                "base_qty": base_qty,
                "quote_qty": net_quote,
                "qty": base_qty,
                "size_pct": size_pct,
                "fee_quote": fee_quote,
                "fee_usd": fee_quote * quote_usd,
                "reason": reason,
                "gain_loss": gain_loss,
            }
        else:
            return None

        return trade
