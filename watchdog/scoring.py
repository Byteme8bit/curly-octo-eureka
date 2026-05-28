"""Health / risk scoring for trade-bot behavior."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class HealthReport:
    score: int
    label: str
    errors_total: int
    errors_last_hour: int
    errors_last_window: int
    bot_errors_last_hour: int
    watchdog_errors_last_hour: int
    drawdown_pct: float
    trades_session: int
    reevaluation_mode: bool
    hibernating: bool
    stale_alert: bool
    watchdog_pauses: int
    factors: tuple[str, ...] = field(default_factory=tuple)
    auto_pause_recommended: bool = False
    auto_pause_reason: str = ""

    def summary_lines(self) -> list[str]:
        lines = [
            f"**Health score: {self.score}/100** — {self.label}",
            f"Trade-bot errors: {self.bot_errors_last_hour} last hour | "
            f"{self.errors_last_window} last burst window | "
            f"{self.errors_total} total",
        ]
        if self.watchdog_errors_last_hour:
            lines.append(
                f"Watchdog self-errors: {self.watchdog_errors_last_hour} last hour "
                "(informational; check `logs/runtime.log`)"
            )
        lines.append(
            f"Drawdown: {self.drawdown_pct:.1%}  |  Session trades: {self.trades_session}"
        )
        if self.watchdog_pauses:
            lines.append(f"Watchdog pauses this session: {self.watchdog_pauses}")
        if self.factors:
            lines.append("")
            lines.append("**Factors:**")
            for factor in self.factors:
                lines.append(f"• {factor}")
        return lines


def _count_recent(timestamps, window_sec: float) -> int:
    cutoff = time.time() - window_sec
    return sum(1 for ts in timestamps if ts >= cutoff)


def compute_health(
    *,
    error_timestamps: list[float],
    drawdown_pct: float,
    trades_session: int,
    reevaluation_mode: bool,
    hibernating: bool,
    stale_alert: bool,
    watchdog_pauses: int,
    error_burst_count: int,
    error_burst_minutes: float,
    auto_pause_score: int,
    watchdog_error_timestamps: list[float] | tuple = (),
    trades_per_hour_high: int = 20,
) -> HealthReport:
    hour_sec = 3600.0
    burst_sec = error_burst_minutes * 60.0

    errors_total = len(error_timestamps)
    errors_hour = _count_recent(error_timestamps, hour_sec)
    errors_burst = _count_recent(error_timestamps, burst_sec)
    wd_errors_hour = _count_recent(list(watchdog_error_timestamps), hour_sec)

    score = 100
    factors: list[str] = []

    if errors_burst > 0:
        penalty = min(45, errors_burst * 12)
        score -= penalty
        factors.append(
            f"{errors_burst} trade-bot error(s) in last {error_burst_minutes:.0f}m (−{penalty})"
        )

    if errors_hour > errors_burst:
        extra = errors_hour - errors_burst
        penalty = min(20, extra * 4)
        score -= penalty
        if penalty:
            factors.append(f"{errors_hour} trade-bot error(s) in last hour (−{penalty})")

    if wd_errors_hour >= 3:
        penalty = min(15, wd_errors_hour * 2)
        score -= penalty
        factors.append(
            f"{wd_errors_hour} watchdog self-error(s) in last hour "
            f"(monitor failing) (−{penalty})"
        )

    if drawdown_pct >= 0.15:
        score -= 45
        factors.append(f"Drawdown {drawdown_pct:.1%} — circuit-breaker zone (−45)")
    elif drawdown_pct >= 0.10:
        score -= 25
        factors.append(f"Drawdown {drawdown_pct:.1%} — elevated (−25)")
    elif drawdown_pct >= 0.05:
        score -= 10
        factors.append(f"Drawdown {drawdown_pct:.1%} (−10)")

    if reevaluation_mode:
        score -= 50
        factors.append("Re-evaluation / circuit-breaker mode active (−50)")

    if hibernating:
        score -= 30
        factors.append("Bot hibernating from drawdown (−30)")

    if stale_alert:
        score -= 25
        factors.append("No recent log activity — bot may be stalled (−25)")

    if trades_session > trades_per_hour_high * 2:
        score -= 10
        factors.append(f"High trade count this session ({trades_session}) (−10)")

    if watchdog_pauses >= 2:
        score -= 15
        factors.append(f"Multiple watchdog pauses ({watchdog_pauses}) (−15)")

    score = max(0, min(100, score))

    if score >= 80:
        label = "Healthy"
    elif score >= 60:
        label = "Normal"
    elif score >= 40:
        label = "Caution — elevated activity"
    elif score >= 20:
        label = "Elevated risk"
    else:
        label = "Critical — too risky"

    too_risky = score < 40 or errors_burst >= error_burst_count or reevaluation_mode

    auto_pause = False
    auto_reason = ""
    if errors_burst >= error_burst_count:
        auto_pause = True
        auto_reason = (
            f"{errors_burst} trade-bot errors in {error_burst_minutes:.0f} minutes "
            f"(limit {error_burst_count})"
        )
    elif score <= auto_pause_score and (errors_hour >= 2 or drawdown_pct >= 0.12):
        auto_pause = True
        auto_reason = f"Health score {score}/100 with compounding risk signals"

    if too_risky and not auto_pause and score <= auto_pause_score:
        factors = (*factors, "Overall behavior flagged as too risky — review before `start`")

    return HealthReport(
        score=score,
        label=label,
        errors_total=errors_total,
        errors_last_hour=errors_hour,
        errors_last_window=errors_burst,
        bot_errors_last_hour=errors_hour,
        watchdog_errors_last_hour=wd_errors_hour,
        drawdown_pct=drawdown_pct,
        trades_session=trades_session,
        reevaluation_mode=reevaluation_mode,
        hibernating=hibernating,
        stale_alert=stale_alert,
        watchdog_pauses=watchdog_pauses,
        factors=tuple(factors) if factors else ("No negative factors detected",),
        auto_pause_recommended=auto_pause,
        auto_pause_reason=auto_reason,
    )
