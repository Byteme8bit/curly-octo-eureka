"""Individual real-world viability checks per trade."""

from __future__ import annotations

from datetime import datetime

import ccxt

from bot.fee_engine import FeeEngine
from bot.portfolio_constraints import CORE_UNCAPPED, PortfolioConstraints
from bot.preflight import PreFlightValidator
from bot.strategies.base import TradeIntent
from bot.verifier.config import VerifierSettings
from bot.verifier.kraken import PublicKraken
from bot.verifier.models import CheckResult, Verdict
from bot.verifier.parsers import (
    estimate_trade_usd,
    find_log_mention,
    parse_receipt_detail,
    receipt_path_for_trade,
    trade_narrative_snippet,
)


def _parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def check_correlation(trade: dict, settings: VerifierSettings) -> CheckResult:
    receipt = receipt_path_for_trade(trade, settings.receipts_dir)
    if receipt is None:
        return CheckResult(
            "existence_correlation",
            Verdict.DENY,
            "No matching receipt file in receipts/",
        )

    detail = parse_receipt_detail(receipt)
    narrative = trade_narrative_snippet(trade)
    if detail and narrative.replace("Traded ", "") not in detail.get("narrative", ""):
        # Receipt narrative is the full line; allow partial asset match.
        if trade["from_asset"] not in detail.get("narrative", ""):
            return CheckResult(
                "existence_correlation",
                Verdict.UNCERTAIN,
                f"Receipt {receipt.name} assets mismatch state trade",
            )

    found_log, log_detail = find_log_mention(
        trade, settings.log_dir, window_minutes=settings.log_time_window_minutes
    )
    if found_log:
        return CheckResult(
            "existence_correlation",
            Verdict.CONFIRM,
            f"Receipt {receipt.name}; {log_detail}",
        )
    return CheckResult(
        "existence_correlation",
        Verdict.UNCERTAIN,
        f"Receipt {receipt.name}; {log_detail}",
    )


def check_market_reality(trade: dict, kraken: PublicKraken | None) -> CheckResult:
    symbol = trade.get("symbol", "")
    from_a = trade.get("from_asset", "")
    to_a = trade.get("to_asset", "")

    if kraken is None:
        return CheckResult("market_reality", Verdict.UNCERTAIN, "Kraken check skipped")

    if not kraken.symbol_exists(symbol):
        return CheckResult("market_reality", Verdict.DENY, f"Pair {symbol} not on Kraken")

    missing = [a for a in (from_a, to_a) if not kraken.asset_tradeable(a)]
    if missing:
        return CheckResult(
            "market_reality",
            Verdict.DENY,
            f"Assets not tradeable on Kraken: {', '.join(missing)}",
        )
    return CheckResult("market_reality", Verdict.CONFIRM, f"Pair {symbol} exists on Kraken")


def check_price_plausibility(
    trade: dict,
    kraken: PublicKraken | None,
    settings: VerifierSettings,
) -> CheckResult:
    if kraken is None:
        return CheckResult("price_plausibility", Verdict.UNCERTAIN, "Kraken check skipped")

    symbol = trade.get("symbol", "")
    price = float(trade.get("price", 0))
    if price <= 0:
        return CheckResult("price_plausibility", Verdict.DENY, "Trade has no positive price")

    trade_time = _parse_time(trade.get("time", ""))
    if trade_time is None:
        return CheckResult("price_plausibility", Verdict.UNCERTAIN, "No trade timestamp for OHLCV")

    low, high, detail = kraken.price_range_at(symbol, trade_time)
    if low is None or high is None:
        return CheckResult("price_plausibility", Verdict.UNCERTAIN, detail)

    tol = settings.price_tolerance_pct + settings.slippage_assume_pct
    min_ok = low * (1.0 - tol)
    max_ok = high * (1.0 + tol)
    if min_ok <= price <= max_ok:
        return CheckResult(
            "price_plausibility",
            Verdict.CONFIRM,
            f"Fill {price:.8g} within {detail} ±{tol:.1%}",
        )
    return CheckResult(
        "price_plausibility",
        Verdict.DENY,
        f"Fill {price:.8g} outside {detail} ±{tol:.1%} — implausible vs market",
    )


def check_fee_realism(
    trade: dict,
    kraken: PublicKraken | None,
    settings: VerifierSettings,
) -> CheckResult:
    applied = float(trade.get("fee_usd", 0))
    symbol = trade.get("symbol", "")
    side = trade.get("side", "buy")
    from_qty = float(trade.get("from_qty", 0))
    quote_qty = float(trade.get("quote_qty", from_qty))

    if kraken is None:
        expected_rate = settings.fee_rate
        source = "env FEE_RATE"
    else:
        expected_rate = kraken.taker_fee(symbol)
        source = f"Kraken taker {symbol}"

    if side == "buy":
        notional_quote = quote_qty
    else:
        notional_quote = from_qty * float(trade.get("price", 0))

    # Approximate USD notional for fee comparison.
    trade_usd = estimate_trade_usd(trade)
    expected_fee_usd = trade_usd * expected_rate if trade_usd > 0 else notional_quote * expected_rate

    if expected_fee_usd <= 0:
        return CheckResult("fee_realism", Verdict.UNCERTAIN, "Could not estimate expected fee")

    rel_err = abs(applied - expected_fee_usd) / expected_fee_usd
    paper_rate = applied / trade_usd if trade_usd > 0 else 0.0

    if expected_fee_usd > 0 and rel_err <= settings.fee_tolerance_rel:
        return CheckResult(
            "fee_realism",
            Verdict.CONFIRM,
            f"Fee ${applied:.2f} ~ expected ${expected_fee_usd:.2f} ({source}, eff {paper_rate:.4%})",
        )

    if abs(paper_rate - settings.fee_rate) < 0.0002:
        return CheckResult(
            "fee_realism",
            Verdict.UNCERTAIN,
            (
                f"Paper used FEE_RATE {settings.fee_rate:.4%} (${applied:.2f}); "
                f"live Kraken would be ~${expected_fee_usd:.2f} ({expected_rate:.4%})"
            ),
        )

    return CheckResult(
        "fee_realism",
        Verdict.DENY,
        f"Fee ${applied:.2f} vs expected ${expected_fee_usd:.2f} ({source}) — off by {rel_err:.0%}",
    )


def check_size_constraints(
    trade: dict,
    settings: VerifierSettings,
    *,
    balances_before: dict[str, float],
    usd_prices: dict[str, float] | None = None,
) -> CheckResult:
    constraints = PortfolioConstraints(
        min_eth_reserve=settings.min_eth_reserve,
        max_alt_allocation_pct=settings.max_alt_allocation_pct,
        min_usd_trade=settings.min_usd_trade,
    )
    prices = usd_prices or {"USD": 1.0}
    intent = TradeIntent(
        from_asset=trade["from_asset"],
        to_asset=trade["to_asset"],
        reason=trade.get("reason", ""),
        size_pct=float(trade.get("size_pct", 0)),
        edge=float(trade.get("edge", 0)),
        is_defensive=bool(trade.get("is_defensive")),
        is_expansion=bool(trade.get("is_expansion")),
        is_held_swap=bool(trade.get("is_held_swap")),
        strategy_name=trade.get("strategy_name", ""),
        gross_return_pct=float(trade.get("gross_return_pct", 0) or trade.get("edge", 0)),
    )
    result = constraints.validate_intent(
        intent, balances_before, prices, required_edge=settings.min_trade_edge
    )
    trade_usd = estimate_trade_usd(trade, prices)

    issues: list[str] = []
    if not result.allowed:
        issues.append(result.reason)

    if trade_usd < settings.min_usd_trade and not trade.get("is_defensive"):
        issues.append(f"Trade USD ${trade_usd:.2f} below MIN_USD_TRADE ${settings.min_usd_trade:.2f}")

    eth_bal = balances_before.get("ETH", 0.0)
    if trade["from_asset"] == "ETH" and trade["from_asset"] == trade["to_asset"]:
        pass  # closed loop — reserve unchanged
    elif trade["from_asset"] == "ETH":
        remaining = eth_bal - float(trade.get("from_qty", 0))
        if remaining < settings.min_eth_reserve - 1e-9:
            issues.append(
                f"Would sell below MIN_ETH_RESERVE ({remaining:.4f} < {settings.min_eth_reserve})"
            )

    if issues:
        worst = Verdict.DENY if any("reserve" in i.lower() or "below minimum" in i.lower() for i in issues) else Verdict.UNCERTAIN
        return CheckResult("size_constraints", worst, "; ".join(issues))

    to_a = trade["to_asset"]
    if to_a not in CORE_UNCAPPED:
        projected = constraints.projected_allocation(
            to_a,
            balances_before,
            prices,
            from_asset=trade["from_asset"],
            to_asset=to_a,
            trade_usd=trade_usd,
        )
        if projected > settings.max_alt_allocation_pct * 1.05:
            return CheckResult(
                "size_constraints",
                Verdict.UNCERTAIN,
                f"{to_a} projected {projected:.1%} > MAX_ALT_ALLOCATION {settings.max_alt_allocation_pct:.0%}",
            )

    return CheckResult(
        "size_constraints",
        Verdict.CONFIRM,
        f"Constraints OK (trade ~${trade_usd:.2f}, ETH reserve {eth_bal:.4f})",
    )


def check_multi_hop(trade: dict) -> CheckResult:
    hops = int(trade.get("hops", 1) or 1)
    trade_type = trade.get("type", "")
    reason = (trade.get("reason") or "").lower()
    strategy = (trade.get("strategy_name") or "").lower()

    flags: list[str] = []
    if trade_type == "multi_hop" or hops > 1:
        flags.append(f"multi-hop route ({hops} legs)")
    if "triangular" in reason or strategy == "triangular_arbitrage":
        flags.append("triangular arbitrage — paper assumes atomic loop")
    if "leg 1/" in reason or "leg 2/" in reason:
        flags.append("partial loop leg — live could stall mid-route")

    if flags:
        return CheckResult(
            "multi_hop_atomic",
            Verdict.UNCERTAIN,
            "; ".join(flags),
        )
    return CheckResult("multi_hop_atomic", Verdict.CONFIRM, "Single-leg or USD pair trade")


def check_preflight(
    trade: dict,
    kraken: PublicKraken | None,
    settings: VerifierSettings,
) -> CheckResult:
    if trade.get("is_defensive"):
        return CheckResult("preflight", Verdict.CONFIRM, "Defensive exit — preflight bypassed in live too")

    gross = float(trade.get("gross_return_pct") or trade.get("edge") or 0)
    legs = trade.get("legs") or []
    if legs:
        route_symbols = tuple(leg.get("symbol", trade.get("symbol", "")) for leg in legs)
    else:
        route_symbols = (trade.get("symbol", ""),)
    hops = int(trade.get("hops", len(route_symbols)) or 1)

    if kraken is None:
        fee_engine = FeeEngine(_StaticExchange(settings.fee_rate), settings.fee_rate, force_static=True)
    else:
        kraken.ensure_markets()
        fee_engine = kraken._fee_engine

    validator = PreFlightValidator(
        fee_engine,
        settings.slippage_buffer_pct,
        settings.min_net_profit_pct,
    )
    intent = TradeIntent(
        from_asset=trade["from_asset"],
        to_asset=trade["to_asset"],
        reason=trade.get("reason", ""),
        size_pct=float(trade.get("size_pct", 0)),
        edge=float(trade.get("edge", 0)),
        gross_return_pct=gross,
        is_defensive=False,
        strategy_name=trade.get("strategy_name", ""),
    )
    result = validator.validate(intent, route_symbols=route_symbols, hops=hops)
    if result.allowed:
        return CheckResult("preflight", Verdict.CONFIRM, result.reason)
    return CheckResult("preflight", Verdict.DENY, result.reason)


def check_liquidity(
    trade: dict,
    kraken: PublicKraken | None,
    settings: VerifierSettings,
    *,
    usd_prices: dict[str, float] | None = None,
) -> CheckResult:
    symbol = trade.get("symbol", "")
    to_a = trade.get("to_asset", "")
    if to_a in CORE_UNCAPPED:
        return CheckResult("liquidity", Verdict.CONFIRM, "Core asset — liquidity check N/A")

    trade_usd = estimate_trade_usd(trade, usd_prices)
    if trade_usd <= 0:
        return CheckResult("liquidity", Verdict.UNCERTAIN, "Could not estimate trade USD size")

    if kraken is None:
        return CheckResult("liquidity", Verdict.UNCERTAIN, "Kraken check skipped")

    vol = kraken.quote_volume_usd(symbol)
    if vol is None or vol <= 0:
        return CheckResult("liquidity", Verdict.UNCERTAIN, f"No 24h volume for {symbol}")

    ratio = trade_usd / vol
    if ratio >= settings.liquidity_volume_warn_ratio:
        return CheckResult(
            "liquidity",
            Verdict.UNCERTAIN,
            f"Trade ${trade_usd:.0f} is {ratio:.2%} of 24h ${symbol} volume — slippage risk",
        )
    return CheckResult(
        "liquidity",
        Verdict.CONFIRM,
        f"Trade ${trade_usd:.0f} is {ratio:.3%} of 24h volume",
    )


class _StaticExchange:
    """Minimal exchange stub for offline preflight replay."""

    def __init__(self, fee: float):
        self._fee = fee
        self._markets: dict = {}

    def load_markets(self):
        return self._markets

    def fetch_trading_fees(self):
        raise ccxt.AuthenticationError("no auth")

    @property
    def markets(self):
        return self._markets

    @markets.setter
    def markets(self, value):
        self._markets = value
