"""Auditor tab — proposals, reports, overrides, chat activity."""

from __future__ import annotations

import re
from pathlib import Path

from bot.auditor.proposer import ALLOWED_KNOBS
from bot.auditor.runtime_overrides import list_overrides
from bot.auditor.state import AuditorState

from dashboard.config import DashboardSettings
from dashboard.io_util import newest_files, read_text, tail_lines

_AUDITOR_CHAT = re.compile(r"Auditor|auditor", re.IGNORECASE)
_REPORT_HEAD = re.compile(r"^# Auditor report — (.+)$", re.MULTILINE)
_NEWS_SECTION = re.compile(
    r"## News headlines\s*\n(.*?)(?=\n## |\Z)",
    re.DOTALL,
)


def _parse_report_summary(path: Path) -> dict | None:
    raw = read_text(path)
    if not raw:
        return None
    head = _REPORT_HEAD.search(raw)
    title = head.group(1).strip() if head else path.stem
    trigger = ""
    m = re.search(r"\*\*Trigger:\*\*\s*`([^`]+)`", raw)
    if m:
        trigger = m.group(1)
    net_pnl = ""
    m2 = re.search(r"\*\*Net PnL:\*\*\s*(\$[^\n]+)", raw)
    if m2:
        net_pnl = m2.group(1).strip()
    proposals = len(re.findall(r"^###\s+`", raw, re.MULTILINE))
    news: list[str] = []
    news_m = _NEWS_SECTION.search(raw)
    if news_m:
        for line in news_m.group(1).splitlines():
            if line.strip().startswith("- **"):
                news.append(line.strip()[:200])
    return {
        "file": path.name,
        "title": title,
        "trigger": trigger,
        "net_pnl": net_pnl,
        "proposal_count": proposals,
        "news_headlines": news[:8],
    }


def _list_audit_reports(reports_dir: Path, *, limit: int = 10) -> list[dict]:
    found: list[tuple[float, Path]] = []
    if not reports_dir.is_dir():
        return []
    for day_dir in reports_dir.iterdir():
        if not day_dir.is_dir():
            continue
        for path in day_dir.glob("audit-*.md"):
            try:
                found.append((path.stat().st_mtime, path))
            except OSError:
                continue
    found.sort(key=lambda x: x[0], reverse=True)
    out: list[dict] = []
    for _, path in found[:limit]:
        row = _parse_report_summary(path)
        if row:
            row["path"] = str(path)
            out.append(row)
    return out


def build_auditor_view(settings: DashboardSettings) -> dict:
    state = AuditorState.load(settings.auditor_state_file)
    overrides = list_overrides(settings.runtime_overrides_file)

    proposals = []
    for pid, p in sorted(state.pending_proposals.items()):
        proposals.append({
            "id": pid,
            "knob": p.knob,
            "current_value": p.current_value,
            "proposed_value": p.proposed_value,
            "severity": p.severity,
            "rationale": p.rationale[:300],
            "created_at": p.created_at,
            "expires_at": p.expires_at,
        })

    override_history = {
        "active": {k: v for k, v in overrides.items()},
        "allowed_knobs": list(ALLOWED_KNOBS),
        "last_auto_apply_at": state.last_auto_apply_at,
        "last_auto_apply_knob": state.last_auto_apply_knob,
        "last_auto_apply_value": state.last_auto_apply_value,
        "last_auto_apply_proposal_id": state.last_auto_apply_proposal_id,
        "auto_applies_this_night": state.auto_applies_this_night,
    }

    chat_lines = [
        ln for ln in tail_lines(settings.discord_chat_log, max_lines=500)
        if _AUDITOR_CHAT.search(ln)
    ][-30:]

    reports = _list_audit_reports(settings.reports_dir)

    latest_news: list[str] = []
    if reports and reports[0].get("news_headlines"):
        latest_news = reports[0]["news_headlines"]

    return {
        "pending_proposals": proposals,
        "run_markers": {
            "last_scheduled_run_at": state.last_scheduled_run_at,
            "last_event_run_at": state.last_event_run_at,
            "last_trade_count_at_event": state.last_trade_count_at_event,
            "last_pnl_at_event": state.last_pnl_at_event,
        },
        "override_history": override_history,
        "recent_reports": reports,
        "news_headlines": latest_news,
        "chat_activity": chat_lines,
        "sources": {
            "state": str(settings.auditor_state_file),
            "overrides": str(settings.runtime_overrides_file),
            "reports": str(settings.reports_dir),
        },
    }
