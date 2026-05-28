"""Track bot-pinned Discord messages and enforce a retention limit."""

from __future__ import annotations

import json
import threading
from pathlib import Path


class PinTracker:
    """Tracks rotating pins plus a dedicated startup pin (exempt from rotation)."""

    def __init__(self, state_file: Path, channel_id: str, max_retain: int):
        self.state_file = state_file
        self.channel_id = channel_id
        self.max_retain = max(1, min(max_retain, 49))
        self._lock = threading.Lock()
        self._ids: list[str] = []
        self._startup_pin_id: str | None = None
        self._load()

    def _load(self) -> None:
        if not self.state_file.exists():
            return
        try:
            with open(self.state_file, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("channel_id") == self.channel_id:
                self._ids = [str(i) for i in data.get("pinned_message_ids", [])]
                raw_startup = data.get("startup_pin_message_id")
                self._startup_pin_id = str(raw_startup) if raw_startup else None
                if self._startup_pin_id and self._startup_pin_id in self._ids:
                    self._ids.remove(self._startup_pin_id)
        except (json.JSONDecodeError, OSError):
            self._ids = []
            self._startup_pin_id = None

    def _save(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "channel_id": self.channel_id,
                    "startup_pin_message_id": self._startup_pin_id,
                    "pinned_message_ids": self._ids,
                },
                f,
                indent=2,
            )

    def startup_pin_id(self) -> str | None:
        with self._lock:
            return self._startup_pin_id

    def set_startup_pin(self, message_id: str) -> str | None:
        """Set startup pin; returns previous startup message id if any."""
        with self._lock:
            previous = self._startup_pin_id
            self._startup_pin_id = str(message_id)
            mid = self._startup_pin_id
            if mid in self._ids:
                self._ids.remove(mid)
            self._save()
            return previous

    def clear_startup_pin(self) -> str | None:
        with self._lock:
            previous = self._startup_pin_id
            self._startup_pin_id = None
            self._save()
            return previous

    def clear_all(self) -> None:
        """Drop every tracked pin id (used on TradeBot -reset)."""
        with self._lock:
            self._ids.clear()
            self._startup_pin_id = None
            self._save()

    def ids(self) -> list[str]:
        with self._lock:
            return list(self._ids)

    def pop_oldest(self) -> str | None:
        with self._lock:
            while self._ids:
                oldest = self._ids.pop(0)
                if oldest == self._startup_pin_id:
                    continue
                self._save()
                return oldest
            return None

    def register(self, message_id: str) -> None:
        with self._lock:
            mid = str(message_id)
            if mid == self._startup_pin_id:
                return
            if mid in self._ids:
                self._ids.remove(mid)
            self._ids.append(mid)
            self._save()

    def remove(self, message_id: str) -> None:
        with self._lock:
            mid = str(message_id)
            if mid == self._startup_pin_id:
                return
            if mid in self._ids:
                self._ids.remove(mid)
                self._save()

    def at_capacity(self) -> bool:
        with self._lock:
            return len(self._ids) >= self.max_retain

    def reconcile(self, live_bot_pin_ids: list[str]) -> None:
        """Drop stale IDs and merge bot pins (startup pin kept separate)."""
        with self._lock:
            live = {str(i) for i in live_bot_pin_ids}
            if self._startup_pin_id and self._startup_pin_id not in live:
                self._startup_pin_id = None
            self._ids = [
                i for i in self._ids
                if i in live and i != self._startup_pin_id
            ]
            for mid in live_bot_pin_ids:
                mid = str(mid)
                if mid == self._startup_pin_id or mid in self._ids:
                    continue
                self._ids.append(mid)
            while len(self._ids) > self.max_retain:
                self._ids.pop(0)
            self._save()
