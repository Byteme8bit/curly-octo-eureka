"""Optional futures tick — momentum on watchlist perps, paper or live."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bot.futures.markets import (
    build_futures_exchange,
    resolve_watchlist_symbols,
    symbol_leverage_cap,
)
from bot.futures.paper_broker import FuturesPaperBroker
from bot.live_guards import is_live_armed

if TYPE_CHECKING:
    from config import Settings

logger = logging.getLogger(__name__)

class FuturesManager:
    """Runs one futures evaluation per engine tick when ENABLE_FUTURES=1."""

    def __init__(self, settings: "Settings"):
        self.settings = settings
        self.symbols: tuple[str, ...] = ()
        self.exchange = build_futures_exchange(
            api_key=settings.api_key if settings.live_futures_enabled else "",
            api_secret=settings.api_secret if settings.live_futures_enabled else "",
            timeout_ms=settings.kraken_request_timeout_ms,
        )
        self.broker: FuturesPaperBroker | None = None
        self._last_prices: dict[str, float] = {}
        self._enabled = settings.enable_futures
        if not self._enabled:
            return
        try:
            markets = self.exchange.load_markets()
            self.symbols = resolve_watchlist_symbols(
                settings.futures_watchlist, markets
            )
        except Exception as exc:
            logger.warning("Futures markets load failed — futures disabled: %s", exc)
            self._enabled = False
            return
        if settings.live_futures_enabled and is_live_armed(
            live_enabled=settings.live_enabled,
            live_trading_confirm=settings.live_trading_confirm,
        ):
            from bot.futures.live_broker import FuturesLiveBroker

            self.broker = FuturesLiveBroker(
                self.exchange,
                settings.futures_live_state_file,
                max_leverage=settings.futures_max_leverage,
                max_position_usd=settings.futures_max_position_usd,
                drawdown_halt_pct=settings.futures_drawdown_halt_pct,
                reset=settings.reset_futures_state,
            )
            self.broker.sync_balance()
            if self.broker.state.balance_usd <= 0:
                logger.error(
                    "FUTURES LIVE armed but wallet balance is $0 — "
                    "Kraken Futures uses separate API keys from spot. "
                    "Create keys at futures.kraken.com or disable LIVE_FUTURES_ENABLED."
                )
            else:
                logger.warning(
                    "FUTURES LIVE ENABLED — real perp orders on %d symbols",
                    len(self.symbols),
                )
        else:
            self.broker = FuturesPaperBroker(
                settings.futures_paper_state_file,
                initial_balance_usd=settings.futures_paper_balance_usd,
                max_leverage=settings.futures_max_leverage,
                max_position_usd=settings.futures_max_position_usd,
                drawdown_halt_pct=settings.futures_drawdown_halt_pct,
                reset=settings.reset_futures_state,
            )
            mode = "RISKY paper" if settings.risky_margin_ok else "paper"
            logger.warning(
                "Futures %s sim on %d symbols (balance $%.0f, lev %.0fx, halt %.0f%%)",
                mode,
                len(self.symbols),
                settings.futures_paper_balance_usd,
                settings.futures_max_leverage,
                settings.futures_drawdown_halt_pct * 100,
            )

    @property
    def active(self) -> bool:
        return self._enabled and self.broker is not None and bool(self.symbols)

    def tick(self) -> list[dict]:
        """Evaluate momentum; at most one open/close per tick. Returns trade records."""
        if not self.active or self.broker.state.halted:
            return []
        trades: list[dict] = []
        try:
            tickers = self.exchange.fetch_tickers(self.symbols)
        except Exception as exc:
            logger.warning("Futures ticker fetch failed: %s", exc)
            return []
        mark_prices: dict[str, float] = {}
        for symbol in self.symbols:
            t = tickers.get(symbol) or {}
            last = float(t.get("last") or t.get("close") or 0.0)
            if last > 0:
                mark_prices[symbol] = last
        if not mark_prices:
            return []
        self.broker.mark_to_market(mark_prices)
        if self.broker.state.halted:
            return []

        for symbol in self.symbols:
            price = mark_prices.get(symbol)
            prev = self._last_prices.get(symbol)
            self._last_prices[symbol] = price
            if price is None or prev is None or prev <= 0:
                continue
            move = (price - prev) / prev
            market = self.exchange.market(symbol)
            lev_cap = symbol_leverage_cap(market, self.settings.futures_max_leverage)
            threshold = self.settings.futures_momentum_threshold
            margin = self.broker.state.balance_usd * self.settings.futures_margin_pct

            if symbol in self.broker.state.positions:
                pos = self.broker.state.positions[symbol]
                if pos.side == "long" and move < -threshold:
                    t = self.broker.close_position(symbol, price, reason="momentum fade")
                    if t:
                        trades.append(t)
                        break
                elif pos.side == "short" and move > threshold:
                    t = self.broker.close_position(symbol, price, reason="momentum fade")
                    if t:
                        trades.append(t)
                        break
            elif abs(move) >= threshold and margin >= 5.0:
                side = "long" if move > 0 else "short"
                t = self.broker.open_position(
                    symbol,
                    side,
                    price,
                    leverage=lev_cap,
                    margin_usd=margin,
                    reason=f"momentum {move:+.3%}",
                )
                if t:
                    trades.append(t)
                    break
        return trades
