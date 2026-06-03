"""Unified chronological activity feed."""

from __future__ import annotations

import re
from datetime import datetime

from dashboard.config import DashboardSettings
from dashboard.parsers.auditor import build_auditor_view
from dashboard.parsers.tradebot import build_tradebot_view
from dashboard.parsers.watchdog import build_watchdog_view

_SEVERITY_ORDER = {"bad": 0, "warn": 1, "info": 2, "good": 3}


def _parse_sort_key(time_str: str) -> tuple:
    s = (time_str or "").strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S %Z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ):
        try:
            chunk = s[: len(fmt.replace("%Z", "PDT"))]
            dt = datetime.strptime(chunk.strip(), fmt.replace(" %Z", ""))
            return (dt.timestamp(), s)
        except ValueError:
            continue
    return (0.0, s)


def _trade_events(tradebot: dict) -> list[dict]:
    out: list[dict] = []
    for t in tradebot.get("recent_trades") or []:
        pnl = t.get("gain_loss_usd")
        severity = "good" if pnl is not None and pnl >= 0 else "bad" if pnl is not None else "info"
        out.append({
            "time": t.get("time", ""),
            "type": "trade",
            "title": t.get("summary") or "Trade",
            "detail": t.get("gain_loss") or "",
            "severity": severity,
        })
    return out


def _watchdog_events(watchdog: dict) -> list[dict]:
    out: list[dict] = []
    for err in watchdog.get("recent_errors") or []:
        msg = err.get("message") or err.get("summary") or str(err)[:120]
        out.append({
            "time": err.get("timestamp") or err.get("time") or "",
            "type": "watchdog",
            "title": "Error",
            "detail": msg,
            "severity": "bad",
        })
    session = watchdog.get("session") or {}
    if session.get("last_watchdog_pause_at"):
        out.append({
            "time": session["last_watchdog_pause_at"],
            "type": "watchdog",
            "title": "Watchdog pause",
            "detail": f"Pauses this session: {session.get('watchdog_pause_count', 0)}",
            "severity": "warn",
        })
    for line in (watchdog.get("alert_lines") or [])[-8:]:
        ts_m = re.match(r"^\[([^\]]+)\]", line)
        ts = ts_m.group(1) if ts_m else ""
        out.append({
            "time": ts,
            "type": "watchdog",
            "title": "Alert",
            "detail": line[:160],
            "severity": "warn" if "pause" in line.lower() else "info",
        })
    return out


def _auditor_events(auditor: dict) -> list[dict]:
    out: list[dict] = []
    for r in auditor.get("recent_reports") or []:
        sev = "info"
        out.append({
            "time": r.get("title", ""),
            "type": "auditor",
            "title": f"Audit ({r.get('trigger', '—')})",
            "detail": f"Net PnL {r.get('net_pnl', '—')} · {r.get('proposal_count', 0)} proposals",
            "severity": sev,
        })
    for p in auditor.get("pending_proposals") or []:
        sev_map = {"high": "bad", "medium": "warn", "low": "info"}
        out.append({
            "time": p.get("created_at") or p.get("expires_at") or "",
            "type": "auditor",
            "title": f"Proposal: {p.get('knob', '')}",
            "detail": f"{p.get('current_value')} → {p.get('proposed_value')} ({p.get('severity', '')})",
            "severity": sev_map.get(str(p.get("severity", "")).lower(), "info"),
        })
    markers = auditor.get("run_markers") or {}
    if markers.get("last_event_run_at"):
        out.append({
            "time": markers["last_event_run_at"],
            "type": "auditor",
            "title": "Event-triggered audit",
            "detail": f"Trades at event: {markers.get('last_trade_count_at_event', '—')}",
            "severity": "info",
        })
    return out


def build_timeline(
    settings: DashboardSettings,
    *,
    tradebot: dict | None = None,
    watchdog: dict | None = None,
    auditor: dict | None = None,
    limit: int = 40,
) -> dict:
    tb = tradebot if tradebot is not None else build_tradebot_view(settings)
    drawdown = 0.0
    if tb.get("portfolio"):
        drawdown = float(tb["portfolio"].get("drawdown_pct", 0.0))
    wd = watchdog if watchdog is not None else build_watchdog_view(settings, drawdown_pct=drawdown)
    au = auditor if auditor is not None else build_auditor_view(settings)

    events: list[dict] = []
    events.extend(_trade_events(tb))
    events.extend(_watchdog_events(wd))
    events.extend(_auditor_events(au))

    events.sort(key=lambda e: _parse_sort_key(e.get("time", "")), reverse=True)
    return {"events": events[:limit], "total": len(events)}
