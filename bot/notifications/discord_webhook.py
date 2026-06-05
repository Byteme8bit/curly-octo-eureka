"""Shared Discord webhook POST helper.

Both ``scripts/post_discord_alert.py`` and ``scripts/monitor_kraken_changes.py``
use this to avoid duplicating urllib JSON-POST logic.

Usage::

    from bot.notifications.discord_webhook import post_webhook

    rc = post_webhook(webhook_url, content="**Hello** from TradeBot", username="Bot")
    # rc == 0 on success, 2 on HTTP/network error

The function never raises — all errors are printed to stderr and reflected
in the return code so callers can propagate exit codes cleanly.
"""

from __future__ import annotations

import json
import sys
import urllib.request

DISCORD_HARD_LIMIT = 2000
SAFETY_HEADROOM = 100


def post_webhook(
    webhook: str,
    *,
    content: str,
    username: str = "TradeBot",
    timeout: int = 10,
) -> int:
    """POST *content* to *webhook*.

    Returns 0 on success, 2 on any HTTP or network error.
    Content longer than ``DISCORD_HARD_LIMIT - SAFETY_HEADROOM`` characters
    is automatically truncated with a trailing marker.
    """
    max_len = DISCORD_HARD_LIMIT - SAFETY_HEADROOM
    if len(content) > max_len:
        content = content[:max_len] + "\n…(truncated — see PR for full detail)"

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
                print(
                    f"ERROR: Discord webhook returned HTTP {resp.status}",
                    file=sys.stderr,
                )
                return 2
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: Discord webhook POST failed: {exc}", file=sys.stderr)
        return 2
    return 0
