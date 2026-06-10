"""Read whale-watch state for the local dashboard."""

from __future__ import annotations

import json
from pathlib import Path

from bot.whale_watch import events_last_24h, prune_events
from dashboard.config import DashboardSettings
from dashboard.io_util import read_text


def _load_state(path: Path) -> dict:
    raw = read_text(path)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def build_whale_view(settings: DashboardSettings) -> dict:
    path = settings.whale_watch_state_file
    data = _load_state(path)
    events = data.get("events") or []
    if not isinstance(events, list):
        events = []
    events = [e for e in events if isinstance(e, dict)]
    events = prune_events(events, max_events=100, max_age_hours=168)
    recent = list(reversed(events[-20:]))
    return {
        "enabled": path.exists(),
        "state_file": str(path),
        "last_check_at": data.get("last_check_at"),
        "count_24h": events_last_24h(events),
        "total_events": len(events),
        "recent_events": recent,
        "config_hint": "Set WHALE_WATCH_ENABLED=1 in .env and restart TradeBot",
    }
