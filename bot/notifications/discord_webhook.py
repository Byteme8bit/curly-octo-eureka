"""Shared Discord webhook helper.

Both ``scripts/post_discord_alert.py`` and ``scripts/monitor_kraken_changes.py``
use this to avoid duplicating the urllib JSON-POST boilerplate.

Public API
----------
post_webhook(webhook, content, *, username, timeout)
    Low-level: send ``content`` to ``webhook``.  Returns 0 on success, 2 on
    Discord error, 3 if webhook is empty/None.

post_alert(title, body, *, webhook, username, timeout)
    Higher-level: formats ``**title**\\nbody``, truncates if needed, then calls
    ``post_webhook``.  Intended for the maintenance-automation script.
"""

from __future__ import annotations

import json
import sys
import urllib.request

DISCORD_HARD_LIMIT = 2000   # Discord rejects messages longer than this
_SAFETY_HEADROOM = 100       # leave room for the "(truncated)" marker
_TRUNC_MARKER = "\n…(truncated — see PR for full detail)"


def post_webhook(
    webhook: str | None,
    content: str,
    *,
    username: str = "TradeBot",
    timeout: int = 10,
) -> int:
    """POST *content* to *webhook*.

    Returns
    -------
    0   success (HTTP 2xx)
    2   Discord returned an error or the network call failed
    3   *webhook* is empty / None — caller should handle missing config
    """
    if not webhook:
        return 3

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
                    f"ERROR: Discord returned HTTP {resp.status}", file=sys.stderr
                )
                return 2
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: Discord post failed: {exc}", file=sys.stderr)
        return 2
    return 0


def post_alert(
    title: str,
    body: str,
    *,
    webhook: str | None,
    username: str = "Auto-Maintenance",
    timeout: int = 10,
) -> int:
    """Format and post a titled alert message.

    Formats as ``**title**\\nbody``, then delegates to :func:`post_webhook`.
    Truncates the combined message if it would exceed Discord's 2 000-char
    limit.

    Returns same codes as :func:`post_webhook`.
    """
    content = f"**{title}**\n{body}"
    max_len = DISCORD_HARD_LIMIT - _SAFETY_HEADROOM
    if len(content) > max_len:
        content = content[:max_len] + _TRUNC_MARKER
    return post_webhook(webhook, content, username=username, timeout=timeout)
