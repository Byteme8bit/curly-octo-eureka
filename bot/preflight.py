"""Pre-flight fee, slippage, and minimum net-profit validation."""

from __future__ import annotations

from dataclasses import dataclass

from bot.fee_engine import FeeEngine
from bot.strategies.base import TradeIntent


@dataclass(frozen=True)
class PreFlightResult:
    allowed: bool
    gross_return_pct: float
    fee_pct: float
    slippage_pct: float
    net_return_pct: float
    reason: str


class PreFlightValidator:
    """
    Intercepts strategy signals before execution.
    Net = Gross - compounded_fees - (slippage * hops)
    """

    def __init__(
        self,
        fee_engine: FeeEngine,
        slippage_buffer_pct: float,
        min_net_profit_pct: float,
    ):
        self.fee_engine = fee_engine
        self.slippage_buffer_pct = slippage_buffer_pct
        self.min_net_profit_pct = min_net_profit_pct

    def validate(
        self,
        intent: TradeIntent,
        *,
        route_symbols: tuple[str, ...],
        hops: int,
        is_defensive: bool = False,
        min_net_profit: float | None = None,
        use_maker_fees: bool = False,
    ) -> PreFlightResult:
        gross = intent.gross_return_pct if intent.gross_return_pct else intent.edge
        fee_pct = (
            self.fee_engine.compounded_maker_fee_pct(route_symbols)
            if use_maker_fees
            else self.fee_engine.compounded_fee_pct(route_symbols)
        )
        slippage_pct = self.slippage_buffer_pct * max(1, hops)
        net = gross - fee_pct - slippage_pct
        threshold = self.min_net_profit_pct if min_net_profit is None else min_net_profit

        if is_defensive:
            return PreFlightResult(
                allowed=True,
                gross_return_pct=gross,
                fee_pct=fee_pct,
                slippage_pct=slippage_pct,
                net_return_pct=net,
                reason="Defensive exit — pre-flight bypass",
            )

        if intent.is_accumulation or intent.strategy_name == "equity_dca":
            return PreFlightResult(
                allowed=True,
                gross_return_pct=gross,
                fee_pct=fee_pct,
                slippage_pct=slippage_pct,
                net_return_pct=net,
                reason="Scheduled accumulation — pre-flight bypass (fee drag only)",
            )

        fee_label = "maker fees" if use_maker_fees else "fees"
        if net <= threshold:
            return PreFlightResult(
                allowed=False,
                gross_return_pct=gross,
                fee_pct=fee_pct,
                slippage_pct=slippage_pct,
                net_return_pct=net,
                reason=(
                    f"Pre-flight reject: net {net:+.4f} "
                    f"(gross {gross:+.4f} - {fee_label} {fee_pct:.4f} - slippage {slippage_pct:.4f}) "
                    f"<= min {threshold:.4f}"
                ),
            )

        ok_label = "maker post-only OK" if use_maker_fees else "Pre-flight OK"
        return PreFlightResult(
            allowed=True,
            gross_return_pct=gross,
            fee_pct=fee_pct,
            slippage_pct=slippage_pct,
            net_return_pct=net,
            reason=f"{ok_label}: net {net:+.4f}",
        )
