"""Thread-safe append-only log of Discord inbound/outbound chat."""

from __future__ import annotations

import threading
from pathlib import Path

from bot.local_time import format_pacific


class DiscordChatLog:
    """Lightweight chat transcript logger.

    Directions:
        "<--"  inbound (user -> bot)
        "-->"  outbound (bot -> channel)
        "..."  outbound pinned message
    """

    def __init__(self, path: Path, enabled: bool = True):
        self.path = path
        self.enabled = enabled
        self._lock = threading.Lock()
        if self.enabled:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def _write(self, line: str) -> None:
        if not self.enabled:
            return
        try:
            with self._lock:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except OSError:
            # Never let chat-log failures break the bot
            pass

    def log_inbound(self, *, user: str, user_id: str, content: str, command: str | None) -> None:
        ts = format_pacific()
        cmd = f" [cmd={command}]" if command else ""
        snippet = _flatten(content)[:500]
        self._write(f"[{ts}] <-- {user} ({user_id}){cmd}: {snippet}")

    def log_outbound(self, *, content: str, pin: bool = False, kind: str = "message") -> None:
        ts = format_pacific()
        arrow = "..." if pin else "-->"
        tag = f"[{kind}{' pin' if pin else ''}]"
        snippet = _flatten(content)[:500]
        self._write(f"[{ts}] {arrow} {tag} {snippet}")

    def log_event(self, message: str) -> None:
        ts = format_pacific()
        self._write(f"[{ts}] === {message}")


def _flatten(text: str) -> str:
    return " | ".join(line.strip() for line in text.splitlines() if line.strip())
