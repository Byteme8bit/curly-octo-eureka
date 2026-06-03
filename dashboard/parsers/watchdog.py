"""WatchDog tab — health score, session stats, alerts, log lines."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from watchdog.scoring import compute_health
from watchdog.state import WatchdogState

from dashboard.config import DashboardSettings
from dashboard.io_util import read_json, tail_lines

_WD_LINE = re.compile(
    r"Watchdog|wd pause|health score|auto-pause|WATCHDOG",
    re.IGNORECASE,
)


def _health_from_state(settings: DashboardSettings, state: WatchdogState, drawdown: float) -> dict:
    report = compute_health(
        error_timestamps=state.error_timestamps,
        watchdog_error_timestamps=state.watchdog_error_timestamps,
        drawdown_pct=drawdown,
        trades_session=state.trades_session,
        reevaluation_mode=False,
        hibernating=False,
        stale_alert=state.stale_alert_sent,
        watchdog_pauses=state.watchdog_pause_count,
        error_burst_count=settings.error_burst_count,
        error_burst_minutes=settings.error_burst_minutes,
        auto_pause_score=settings.auto_pause_score,
    )
    return {
        "score": report.score,
        "label": report.label,
        "errors_last_hour": report.errors_last_hour,
        "errors_last_window": report.errors_last_window,
        "watchdog_errors_last_hour": report.watchdog_errors_last_hour,
        "drawdown_pct": report.drawdown_pct,
        "trades_session": report.trades_session,
        "watchdog_pauses": report.watchdog_pauses,
        "factors": list(report.factors),
        "auto_pause_recommended": report.auto_pause_recommended,
        "auto_pause_reason": report.auto_pause_reason,
    }


def _filter_watchdog_lines(lines: list[str], *, limit: int = 50) -> list[str]:
    out: list[str] = []
    for line in reversed(lines):
        if _WD_LINE.search(line):
            out.append(line)
            if len(out) >= limit:
                break
    out.reverse()
    return out


def build_watchdog_view(
    settings: DashboardSettings,
    *,
    drawdown_pct: float = 0.0,
) -> dict:
    state = WatchdogState.load(settings.watchdog_state_file)
    health = _health_from_state(settings, state, drawdown_pct)

    discord_lines = tail_lines(settings.discord_chat_log, max_lines=600)
    runtime_lines = tail_lines(settings.runtime_log, max_lines=600)
    alert_lines = _filter_watchdog_lines(discord_lines + runtime_lines)

    hb_age = None
    if state.last_heartbeat_at > 1_000_000_000:
        hb_age = int(datetime.now(timezone.utc).timestamp() - state.last_heartbeat_at)

    return {
        "health": health,
        "session": {
            "running": state.running,
            "session_started_at": state.session_started_at,
            "trades_session": state.trades_session,
            "watchdog_pause_count": state.watchdog_pause_count,
            "last_watchdog_pause_at": state.last_watchdog_pause_at,
            "last_portfolio": state.last_portfolio,
            "last_baseline": state.last_baseline,
            "stale_alert_sent": state.stale_alert_sent,
            "seen_receipts_count": len(state.seen_receipts),
            "heartbeat_age_sec": hb_age,
        },
        "recent_errors": list(state.recent_errors[-15:]),
        "alert_lines": alert_lines,
        "sources": {
            "state": str(settings.watchdog_state_file),
            "runtime_log": str(settings.runtime_log),
            "discord_chat": str(settings.discord_chat_log),
        },
    }
