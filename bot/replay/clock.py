"""Injectable clock for historical replay."""

from __future__ import annotations

from datetime import datetime, timezone


class ReplayClock:
    """Wall-clock stand-in advanced by the replay runner."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime.now(timezone.utc)

    def now(self) -> datetime:
        return self._now

    def advance(self, ts: datetime) -> None:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        self._now = ts

    def isoformat(self) -> str:
        return self._now.isoformat()
