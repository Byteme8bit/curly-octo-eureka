"""Fast per-trade live-viability tag for Discord trade posts."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from bot.fee_engine import FeeEngine
from bot.preflight import PreFlightValidator
from bot.strategies.base import TradeIntent
from bot.verifier.kraken import PublicKraken
from bot.verifier.models import Verdict
from bot.verifier.parsers import estimate_trade_usd

logger = logging.getLogger(__name__)

_PRICE_TOLERANCE = 0.03  # 3% vs live ticker for fast check


class MarketChecker(Protocol):
    def symbol_exists(self, symbol: str) -> bool: ...


@dataclass(frozen=True)
class LiveVerifyResult:
    tag: str
    verdict: Verdict
    source: str = "Kraken public fees + ticker"


def _route_symbols(trade: dict) -> tuple[str, ...]:
    legs = trade.get("legs") or []
    if legs:
        return tuple(leg.get("symbol", trade.get("symbol", "")) for leg in legs)
    symbol = trade.get("symbol", "")
    return (symbol,) if symbol else ()


def is_multi_hop_trade(trade: dict) -> bool:
    hops = int(trade.get("hops", 1) or 1)
    trade_type = trade.get("type", "")
    reason = (trade.get("reason") or "").lower()
    strategy = (trade.get("strategy_name") or "").lower()
    if trade_type == "multi_hop" or hops > 1:
        return True
    if "triangular" in reason or strategy == "triangular_arbitrage":
        return True
    if "leg 1/" in reason or "leg 2/" in reason:
        return True
    return False


def _estimate_net_usd(trade: dict, net_return_pct: float, usd_prices: dict[str, float] | None) -> float:
    trade_usd = estimate_trade_usd(trade, usd_prices)
    if trade_usd <= 0:
        return float(trade.get("gain_loss", 0.0))
    return trade_usd * net_return_pct


def build_live_verify_tag(
    trade: dict,
    *,
    markets: MarketChecker | None = None,
    kraken: PublicKraken | None = None,
    fee_engine: FeeEngine | None = None,
    preflight: PreFlightValidator | None = None,
    usd_prices: dict[str, float] | None = None,
    skip_kraken: bool = False,
) -> LiveVerifyResult:
    """Run lightweight live-viability checks and return a Discord footer line."""
    if trade.get("live") and trade.get("order_id"):
        oid = trade["order_id"]
        symbol = trade.get("symbol", "")
        return LiveVerifyResult(
            tag=f"✓ Live fill confirmed on Kraken ({symbol} order {oid})",
            verdict=Verdict.CONFIRM,
            source="Kraken exchange fill",
        )

    source = "Kraken public fees + ticker"
    route_symbols = _route_symbols(trade)
    symbol = trade.get("symbol", route_symbols[0] if route_symbols else "")

    if is_multi_hop_trade(trade):
        return LiveVerifyResult(
            tag="⚠ Paper-only / multi-hop — live execution uncertain",
            verdict=Verdict.UNCERTAIN,
            source=source,
        )

    if trade.get("is_accumulation") or trade.get("strategy_name") == "equity_dca":
        return LiveVerifyResult(
            tag="✓ Scheduled equity DCA — single-leg USD buy (accumulation)",
            verdict=Verdict.CONFIRM,
            source=source,
        )

    if not route_symbols or not symbol:
        return LiveVerifyResult(
            tag="✗ Would likely fail live: no route symbol",
            verdict=Verdict.DENY,
            source=source,
        )

    if markets is not None and not markets.symbol_exists(symbol):
        return LiveVerifyResult(
            tag=f"✗ Would likely fail live: pair {symbol} not on exchange",
            verdict=Verdict.DENY,
            source=source,
        )

    if kraken is not None and not skip_kraken:
        try:
            if not kraken.symbol_exists(symbol):
                return LiveVerifyResult(
                    tag=f"✗ Would likely fail live: {symbol} not on Kraken",
                    verdict=Verdict.DENY,
                    source=source,
                )
            fill_price = float(trade.get("price", 0))
            if fill_price > 0:
                ticker = kraken.exchange.fetch_ticker(symbol)
                last = float(ticker.get("last") or 0)
                if last > 0:
                    rel = abs(fill_price - last) / last
                    if rel > _PRICE_TOLERANCE:
                        return LiveVerifyResult(
                            tag=(
                                f"✗ Would likely fail live: fill {fill_price:.6g} "
                                f"vs Kraken {last:.6g} ({rel:.1%} off)"
                            ),
                            verdict=Verdict.DENY,
                            source=source,
                        )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Live verify ticker check failed for %s: %s", symbol, exc)
            source = "fee engine (ticker unavailable)"

    net_return_pct = float(trade.get("edge", 0) or trade.get("gross_return_pct", 0))
    fee_pct = 0.0
    hops = int(trade.get("hops", len(route_symbols)) or 1)

    if preflight is not None and fee_engine is not None:
        fee_pct = fee_engine.compounded_fee_pct(route_symbols)
        slippage_pct = preflight.slippage_buffer_pct * max(1, hops)
        gross = float(trade.get("gross_return_pct") or trade.get("edge") or 0)
        net_return_pct = gross - fee_pct - slippage_pct
        if not trade.get("is_defensive"):
            intent = TradeIntent(
                from_asset=trade["from_asset"],
                to_asset=trade["to_asset"],
                reason=trade.get("reason", ""),
                size_pct=float(trade.get("size_pct", 0)),
                edge=float(trade.get("edge", 0)),
                gross_return_pct=gross,
                strategy_name=trade.get("strategy_name", ""),
                is_accumulation=bool(
                    trade.get("is_accumulation")
                    or trade.get("strategy_name") == "equity_dca"
                ),
            )
            pf = preflight.validate(
                intent,
                route_symbols=route_symbols,
                hops=hops,
                is_defensive=bool(trade.get("is_defensive")),
            )
            net_return_pct = pf.net_return_pct
            if not pf.allowed:
                return LiveVerifyResult(
                    tag=f"✗ Would likely fail live: {pf.reason}",
                    verdict=Verdict.DENY,
                    source=source,
                )

    net_usd = _estimate_net_usd(trade, net_return_pct, usd_prices)
    sign = "+" if net_usd >= 0 else ""
    return LiveVerifyResult(
        tag=f"✓ Live-viable est. net {sign}${net_usd:.2f} after fees ({source})",
        verdict=Verdict.CONFIRM,
        source=source,
    )
