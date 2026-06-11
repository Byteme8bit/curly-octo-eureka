"""Data models for verification reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Verdict(str, Enum):
    CONFIRM = "CONFIRM"
    DENY = "DENY"
    UNCERTAIN = "UNCERTAIN"

    @classmethod
    def worst(cls, *values: Verdict) -> Verdict:
        order = {cls.CONFIRM: 0, cls.UNCERTAIN: 1, cls.DENY: 2}
        return max(values, key=lambda v: order[v])


@dataclass
class CheckResult:
    name: str
    verdict: Verdict
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "verdict": self.verdict.value, "detail": self.detail}


@dataclass
class TradeVerdict:
    trade_index: int
    time: str
    from_asset: str
    to_asset: str
    symbol: str
    reason: str
    verdict: Verdict
    checks: list[CheckResult] = field(default_factory=list)
    receipt_file: str | None = None
    trade_usd: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_index": self.trade_index,
            "time": self.time,
            "from_asset": self.from_asset,
            "to_asset": self.to_asset,
            "symbol": self.symbol,
            "reason": self.reason,
            "verdict": self.verdict.value,
            "receipt_file": self.receipt_file,
            "trade_usd": self.trade_usd,
            "checks": [c.to_dict() for c in self.checks],
        }


@dataclass
class SessionReport:
    generated_at: str
    trades_reviewed: int
    confirm: int
    deny: int
    uncertain: int
    paper_pnl_usd: float
    estimated_fee_drag_usd: float
    systematic_issues: list[str] = field(default_factory=list)
    trade_verdicts: list[TradeVerdict] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "trades_reviewed": self.trades_reviewed,
            "summary": {
                "confirm": self.confirm,
                "deny": self.deny,
                "uncertain": self.uncertain,
            },
            "paper_pnl_usd": round(self.paper_pnl_usd, 2),
            "estimated_fee_drag_usd": round(self.estimated_fee_drag_usd, 2),
            "systematic_issues": self.systematic_issues,
            "sources": self.sources,
            "trades": [t.to_dict() for t in self.trade_verdicts],
        }
