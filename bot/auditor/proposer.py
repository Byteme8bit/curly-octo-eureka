"""Tier-2 config proposals derived from auditor insights.

Hard safety rails:
- Only the five knobs listed in ``ALLOWED_KNOBS`` are ever proposed.
- The proposer NEVER writes to disk; it returns suggestions for the
  service layer to surface to the user. Confirmation + apply happens in
  ``runtime_overrides.apply_proposal``.
- Every proposal carries an `expires_at` so stale recommendations time out.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from bot.auditor.analyzer import PortfolioInsights, StrategyPerformance
from bot.auditor.forecaster import ForecastBand
from bot.local_time import format_pacific, pacific_now, to_pacific


ALLOWED_KNOBS: tuple[str, ...] = (
    "MIN_TRADE_EDGE",
    "TRADE_SIZE_PCT",
    "MIN_NET_PROFIT_PCT",
    "IDLE_REEVAL_HOURS",
    "STRATEGY_EXPLORATION_RATIO",
)

# Knob -> Settings attribute name. Kept here next to ALLOWED_KNOBS so the
# proposer can read the current value without importing config logic.
KNOB_TO_FIELD: dict[str, str] = {
    "MIN_TRADE_EDGE": "min_trade_edge",
    "TRADE_SIZE_PCT": "trade_size_pct",
    "MIN_NET_PROFIT_PCT": "min_net_profit_pct",
    "IDLE_REEVAL_HOURS": "idle_reeval_hours",
    "STRATEGY_EXPLORATION_RATIO": "strategy_exploration_ratio",
}


@dataclass(frozen=True)
class ConfigProposal:
    id: str
    knob: str
    current_value: float
    proposed_value: float
    rationale: str
    created_at: str
    expires_at: str
    severity: str            # "low" | "medium" | "high"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "knob": self.knob,
            "current_value": self.current_value,
            "proposed_value": self.proposed_value,
            "rationale": self.rationale,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "severity": self.severity,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ConfigProposal":
        return cls(
            id=str(data["id"]),
            knob=str(data["knob"]),
            current_value=float(data["current_value"]),
            proposed_value=float(data["proposed_value"]),
            rationale=str(data.get("rationale", "")),
            created_at=str(data.get("created_at", "")),
            expires_at=str(data.get("expires_at", "")),
            severity=str(data.get("severity", "low")),
        )


def _short_id() -> str:
    return uuid.uuid4().hex[:8]


def _proposal(
    knob: str,
    current: float,
    proposed: float,
    rationale: str,
    severity: str,
    ttl_minutes: int,
) -> ConfigProposal:
    now = pacific_now()
    expires = now + timedelta(minutes=max(1, ttl_minutes))
    return ConfigProposal(
        id=_short_id(),
        knob=knob,
        current_value=float(current),
        proposed_value=float(proposed),
        rationale=rationale,
        created_at=format_pacific(now),
        expires_at=format_pacific(expires),
        severity=severity,
    )


def _current(settings, field: str, default: float = 0.0) -> float:
    return float(getattr(settings, field, default))


def _dominant_strategy(by_strategy: list[StrategyPerformance]) -> StrategyPerformance | None:
    if not by_strategy:
        return None
    return max(by_strategy, key=lambda s: s.total_pnl)


def propose_changes(
    insights: PortfolioInsights,
    forecast: list[ForecastBand],
    current_settings,
    *,
    allowed_knobs: tuple[str, ...] = ALLOWED_KNOBS,
    ttl_minutes: int = 60,
) -> list[ConfigProposal]:
    """Generate tier-2 config proposals from insights + forecast.

    Heuristic-only. Returns an empty list when the data doesn't justify any
    proposal — silence is a valid answer.
    """
    proposals: list[ConfigProposal] = []

    def _allowed(knob: str) -> bool:
        return knob in allowed_knobs

    if not insights.by_strategy or insights.total_trades == 0:
        return proposals

    # 1) High fee drag -> raise edge + min net profit
    aggregate_abs_pnl = abs(insights.total_pnl) or 1e-9
    aggregate_drag = insights.total_fees / aggregate_abs_pnl
    if aggregate_drag > 1.0 and insights.total_trades >= 5:
        if _allowed("MIN_TRADE_EDGE"):
            current = _current(current_settings, "min_trade_edge", 0.006)
            proposed = round(current * 1.25, 6)
            proposals.append(
                _proposal(
                    "MIN_TRADE_EDGE",
                    current,
                    proposed,
                    f"Fee drag {aggregate_drag:.2f}x absolute PnL on {insights.total_trades} trades — raise edge requirement 25%.",
                    "medium",
                    ttl_minutes,
                )
            )
        if _allowed("MIN_NET_PROFIT_PCT"):
            current = _current(current_settings, "min_net_profit_pct", 0.0005)
            proposed = round(max(current * 1.5, current + 0.0005), 6)
            proposals.append(
                _proposal(
                    "MIN_NET_PROFIT_PCT",
                    current,
                    proposed,
                    "Fee drag dominates absolute PnL — tighten net-profit floor so only stronger setups trade.",
                    "medium",
                    ttl_minutes,
                )
            )

    # 2) Low win rate across plenty of data -> shrink trade size
    if insights.total_trades >= 30 and insights.win_rate < 0.45:
        if _allowed("TRADE_SIZE_PCT"):
            current = _current(current_settings, "trade_size_pct", 0.10)
            proposed = round(max(0.01, current * 0.90), 6)
            if proposed < current:
                proposals.append(
                    _proposal(
                        "TRADE_SIZE_PCT",
                        current,
                        proposed,
                        f"Win rate {insights.win_rate:.0%} over {insights.total_trades} trades — reduce position size 10%.",
                        "medium",
                        ttl_minutes,
                    )
                )

    # 3) Dominant winning strategy -> reduce exploration
    dominant = _dominant_strategy(insights.by_strategy)
    if (
        dominant
        and dominant.trade_count >= 20
        and dominant.win_rate >= 0.55
        and dominant.total_pnl > 0
        and _allowed("STRATEGY_EXPLORATION_RATIO")
    ):
        current = _current(current_settings, "strategy_exploration_ratio", 0.25)
        proposed = round(max(0.0, current * 0.5), 6)
        if proposed < current:
            proposals.append(
                _proposal(
                    "STRATEGY_EXPLORATION_RATIO",
                    current,
                    proposed,
                    f"`{dominant.strategy}` carrying {dominant.trade_count} trades @ {dominant.win_rate:.0%} win rate — halve exploration ratio.",
                    "low",
                    ttl_minutes,
                )
            )

    # 4) Forecast points to negative expected value across all horizons -> tighten
    if forecast and all(b.expected_pnl < 0 for b in forecast if b.method != "insufficient_data"):
        bands_used = [b for b in forecast if b.method != "insufficient_data"]
        if bands_used and _allowed("MIN_TRADE_EDGE"):
            current = _current(current_settings, "min_trade_edge", 0.006)
            proposed = round(current * 1.15, 6)
            if not any(p.knob == "MIN_TRADE_EDGE" for p in proposals):
                worst = min(b.expected_pnl for b in bands_used)
                proposals.append(
                    _proposal(
                        "MIN_TRADE_EDGE",
                        current,
                        proposed,
                        f"Forecast central tendency negative across horizons (worst ${worst:,.2f}) — tighten edge 15%.",
                        "high",
                        ttl_minutes,
                    )
                )

    return proposals
