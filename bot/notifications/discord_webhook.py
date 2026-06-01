"""Shared Discord webhook poster used by scripts and the auditor.

All callers that need to fire-and-forget a JSON-POST to a Discord webhook
should use :func:`post_webhook` rather than reimplementing urllib boilerplate.

Exit semantics (for CLI callers):
  ``post_webhook`` raises ``DiscordWebhookError`` on failure so callers can
  translate that to whatever exit code they need.
"""

from __future__ import annotations

import json
import urllib.request


DISCORD_HARD_LIMIT = 2000  # Discord rejects messages longer than this
SAFETY_HEADROOM = 100      # leave room for a "(truncated)" suffix


class DiscordWebhookError(RuntimeError):
    """Raised when the Discord POST fails or returns a non-2xx status."""


def post_webhook(
    webhook: str,
    content: str,
    *,
    username: str = "TradeBot",
    timeout: int = 10,
) -> None:
    """POST *content* to *webhook*.

    Automatically truncates *content* to stay within Discord's 2000-char
    limit.  Raises :class:`DiscordWebhookError` on network error or a
    non-2xx HTTP response.
    """
    max_len = DISCORD_HARD_LIMIT - SAFETY_HEADROOM
    if len(content) > max_len:
        content = content[:max_len] + "\n…(truncated)"

    payload = json.dumps({"username": username, "content": content}).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status >= 300:
                raise DiscordWebhookError(f"Discord returned HTTP {resp.status}")
    except DiscordWebhookError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DiscordWebhookError(f"Discord POST failed: {exc}") from exc
