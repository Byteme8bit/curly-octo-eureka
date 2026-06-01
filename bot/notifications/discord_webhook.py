"""Centralised Discord webhook poster.

Both ``scripts/post_discord_alert.py`` and ``scripts/monitor_kraken_changes.py``
previously duplicated the same urllib JSON-POST logic.  This module is the
single implementation; both scripts now delegate here.

Usage::

    from bot.notifications.discord_webhook import post_webhook

    ok = post_webhook(webhook_url, content="**Hello** from TradeBot")
    ok = post_webhook(webhook_url, content=body, username="Kraken Monitor")

The function returns ``True`` on a 2xx response and ``False`` on any network
or HTTP error (errors are logged at WARNING level so callers can stay simple).
"""

from __future__ import annotations

import json
import logging
import urllib.request

logger = logging.getLogger(__name__)

# Discord rejects payloads whose ``content`` field exceeds 2000 characters.
DISCORD_MAX_CHARS = 2000
_TRUNCATION_SUFFIX = "\n…(truncated)"


def post_webhook(
    webhook: str,
    content: str,
    *,
    username: str = "TradeBot",
    timeout: int = 10,
) -> bool:
    """POST *content* to a Discord webhook URL.

    Parameters
    ----------
    webhook:
        Full Discord webhook URL (``https://discord.com/api/webhooks/…``).
    content:
        Message body.  Markdown is supported.  Will be silently truncated to
        fit within Discord's 2000-character hard limit.
    username:
        Display name shown in the Discord channel for this post.
    timeout:
        HTTP request timeout in seconds (default 10).

    Returns
    -------
    bool
        ``True`` if Discord returned a 2xx status, ``False`` otherwise.
    """
    webhook = webhook.strip()
    if not webhook:
        logger.warning("post_webhook: no webhook URL supplied — skipping")
        return False

    if len(content) > DISCORD_MAX_CHARS - len(_TRUNCATION_SUFFIX):
        cut = DISCORD_MAX_CHARS - len(_TRUNCATION_SUFFIX)
        content = content[:cut] + _TRUNCATION_SUFFIX

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
                logger.warning(
                    "post_webhook: Discord returned HTTP %s", resp.status
                )
                return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("post_webhook: request failed: %s", exc)
        return False
    return True
