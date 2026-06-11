"""Executive LIVE_READY assessment for verification reports."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module

from bot.verifier.models import SessionReport, Verdict

# Fraction of reviewed trades with correlation DENY → data integrity failed.
INTEGRITY_DENY_TRADE_PCT = 0.05

# Fraction of trades flagged multi-hop/triangular → not live-safe.
TRIANGULAR_MAJORITY_PCT = 0.50

# When DENY checks exist, fraction that are price/fee → unrealistic paper fills.
PRICE_FEE_DENY_CHECK_MAJORITY = 0.50

# Overall trade-level DENY rate above this → hard NO.
OVERALL_DENY_RATE_NO = 0.20


@dataclass(frozen=True)
class LiveReadyAssessment:
    level: str  # "NO", "CONDITIONAL", "YES"
    headline: str
    reasons: list[str]
    paper_only: bool


def codebase_has_live_broker() -> bool:
    """True only when a real-money broker module is importable."""
    try:
        import_module("bot.live_broker")
    except ImportError:
        return False
    return True


def assess_live_ready(report: SessionReport) -> LiveReadyAssessment:
    """Blunt go/no-go summary for paper trust and live-money readiness."""
    n = max(report.trades_reviewed, 1)
    reasons: list[str] = []
    paper_only = not codebase_has_live_broker()

    if paper_only:
        reasons.append(
            "No live broker in codebase — real-money trading not supported"
        )

    integrity_deny_trades = sum(
        1
        for tv in report.trade_verdicts
        if any(
            c.name == "existence_correlation" and c.verdict == Verdict.DENY
            for c in tv.checks
        )
    )
    price_fee_denies = 0
    total_deny_checks = 0
    triangular_count = sum(
        1
        for tv in report.trade_verdicts
        if any(
            c.name == "multi_hop_atomic" and c.verdict == Verdict.UNCERTAIN
            for c in tv.checks
        )
    )

    for tv in report.trade_verdicts:
        for check in tv.checks:
            if check.verdict != Verdict.DENY:
                continue
            total_deny_checks += 1
            if check.name in ("price_plausibility", "fee_realism"):
                price_fee_denies += 1

    integrity_failed = integrity_deny_trades / n > INTEGRITY_DENY_TRADE_PCT
    if integrity_failed:
        reasons.append(
            "Data integrity failed — missing or mismatched receipts/logs"
        )

    price_fee_dominates = (
        total_deny_checks > 0
        and price_fee_denies / total_deny_checks > PRICE_FEE_DENY_CHECK_MAJORITY
    )
    if price_fee_dominates and report.deny > 0:
        reasons.append(
            "Paper fills not realistic — price/fee DENY dominates vs Kraken"
        )

    triangular_majority = triangular_count / n > TRIANGULAR_MAJORITY_PCT
    if triangular_majority:
        reasons.append(
            "Multi-hop/triangular routes dominate — not live-safe without atomic execution"
        )

    deny_rate = report.deny / n

    hard_no = (
        integrity_failed
        or triangular_majority
        or deny_rate > OVERALL_DENY_RATE_NO
        or (price_fee_dominates and deny_rate > 0.10)
    )

    if hard_no:
        level = "NO"
        headline = "LIVE_READY: NO — DO NOT TRADE"
    elif (
        report.deny == 0
        and report.uncertain <= max(1, int(n * 0.10))
        and not triangular_majority
        and not integrity_failed
    ):
        level = "YES"
        headline = "LIVE_READY: YES — paper session verified"
    else:
        level = "CONDITIONAL"
        headline = "LIVE_READY: CONDITIONAL — review before trusting paper PnL"

    return LiveReadyAssessment(
        level=level,
        headline=headline,
        reasons=reasons,
        paper_only=paper_only,
    )


def format_executive_banner(report: SessionReport) -> str:
    """Multi-line executive summary with verdict banner."""
    assessment = assess_live_ready(report)
    bar = "=" * 60
    lines = [
        bar,
        assessment.headline,
        bar,
        (
            f"CONFIRM {report.confirm} | DENY {report.deny} | "
            f"UNCERTAIN {report.uncertain} ({report.trades_reviewed} trades reviewed)"
        ),
        f"Paper PnL (reviewed): ${report.paper_pnl_usd:,.2f} | "
        f"Fee drag: ${report.estimated_fee_drag_usd:,.2f}",
    ]
    if assessment.reasons:
        lines.append("")
        lines.append("WHY:")
        for reason in assessment.reasons:
            lines.append(f"  • {reason}")
    for issue in report.systematic_issues[:3]:
        lines.append(f"  • {issue}")
    lines.append(bar)
    return "\n".join(lines)


def format_summary_one_line(report: SessionReport) -> str:
    """Single-line summary for scripts and `--summary-only`."""
    assessment = assess_live_ready(report)
    primary = assessment.reasons[0] if assessment.reasons else "checks passed"
    return (
        f"{assessment.headline} | "
        f"CONFIRM {report.confirm}/DENY {report.deny}/UNCERTAIN {report.uncertain} "
        f"({report.trades_reviewed} trades) | {primary}"
    )


def format_discord_verify_summary(report: SessionReport, json_path) -> str:
    """Compact Discord post — executive summary only, not per-trade dump."""
    assessment = assess_live_ready(report)
    lines = [
        f"**{assessment.headline}**",
        "",
        (
            f"CONFIRM **{report.confirm}** | DENY **{report.deny}** | "
            f"UNCERTAIN **{report.uncertain}** "
            f"({report.trades_reviewed} trades reviewed)"
        ),
        (
            f"Paper PnL: ${report.paper_pnl_usd:,.2f} | "
            f"Fee drag: ${report.estimated_fee_drag_usd:,.2f}"
        ),
    ]
    if assessment.reasons:
        lines.append("")
        lines.append("**Why:**")
        for reason in assessment.reasons[:5]:
            lines.append(f"• {reason}")
    for issue in report.systematic_issues[:2]:
        lines.append(f"• {issue}")
    lines.append("")
    lines.append(f"_Full JSON: `{json_path}`_")
    body = "\n".join(lines)
    if len(body) > 1900:
        body = body[:1890] + "\n…"
    return body
