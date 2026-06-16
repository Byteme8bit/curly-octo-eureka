"""Live Kraken Futures execution — gated by LIVE_FUTURES_ENABLED."""

from __future__ import annotations

import logging
from typing import Any

import ccxt

from bot.futures.paper_broker import FuturesPaperBroker

logger = logging.getLogger(__name__)


class FuturesLiveBroker(FuturesPaperBroker):
    """Execute perp orders on Kraken Futures; inherits paper state tracking."""

    def __init__(
        self,
        exchange: ccxt.krakenfutures,
        state_file,
        *,
        max_leverage: float = 5.0,
        max_position_usd: float = 100.0,
        drawdown_halt_pct: float = 0.10,
        fee_rate: float = 0.0005,
        reset: bool = False,
    ):
        super().__init__(
            state_file,
            initial_balance_usd=0.0,
            max_leverage=max_leverage,
            max_position_usd=max_position_usd,
            drawdown_halt_pct=drawdown_halt_pct,
            fee_rate=fee_rate,
            reset=reset,
        )
        self.exchange = exchange

    def sync_balance(self) -> None:
        try:
            raw = self.exchange.fetch_balance()
        except ccxt.BaseError as exc:
            logger.warning("Futures balance sync failed: %s", exc)
            return
        usd = float((raw.get("total") or {}).get("USD") or 0.0)
        if usd > 0:
            self.state.balance_usd = usd
            self.save()

    def open_position(
        self,
        symbol: str,
        side: str,
        price: float,
        *,
        leverage: float,
        margin_usd: float,
        reason: str = "",
    ) -> dict | None:
        if self.state.halted or price <= 0 or margin_usd <= 0:
            return None
        if symbol in self.state.positions:
            return None
        lev = min(leverage, self.max_leverage)
        notional = min(margin_usd * lev, self.max_position_usd)
        contracts = notional / price
        amount = float(self.exchange.amount_to_precision(symbol, contracts))
        market = self.exchange.market(symbol)
        min_amt = (market.get("limits") or {}).get("amount", {}).get("min")
        if min_amt and amount < float(min_amt):
            return None
        order_side = "buy" if side == "long" else "sell"
        params: dict[str, Any] = {"leverage": int(lev)}
        try:
            order = self.exchange.create_order(
                symbol, "market", order_side, amount, params=params
            )
        except ccxt.BaseError as exc:
            logger.error("Futures live open failed on %s: %s", symbol, exc)
            return None
        filled = float(order.get("filled") or amount)
        avg = float(order.get("average") or order.get("price") or price)
        margin_used = notional / lev
        return super().open_position(
            symbol,
            side,
            avg,
            leverage=lev,
            margin_usd=margin_used,
            reason=f"[live] {reason}",
        )

    def close_position(self, symbol: str, price: float, *, reason: str = "") -> dict | None:
        pos = self.state.positions.get(symbol)
        if not pos:
            return None
        close_side = "sell" if pos.side == "long" else "buy"
        amount = float(self.exchange.amount_to_precision(symbol, pos.contracts))
        try:
            order = self.exchange.create_order(symbol, "market", close_side, amount)
        except ccxt.BaseError as exc:
            logger.error("Futures live close failed on %s: %s", symbol, exc)
            self.halt(f"Failed to close {symbol}: {exc}")
            return None
        avg = float(order.get("average") or order.get("price") or price)
        return super().close_position(symbol, avg, reason=f"[live] {reason}")
