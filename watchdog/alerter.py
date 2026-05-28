"""Discord webhook alerts for the watchdog."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


class DiscordAlerter:
    def __init__(self, webhook_url: str, *, pin_major: bool = False):
        self.webhook_url = webhook_url.strip()
        self.pin_major = pin_major

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url)

    def post(self, content: str, *, pin: bool = False) -> bool:
        if not self.enabled:
            logger.warning("Discord webhook not configured — alert skipped")
            return False
        payload: dict = {"content": content[:2000]}
        if pin and self.pin_major:
            payload["flags"] = 4  # suppress embeds; pin requires bot API — webhook can't pin
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.webhook_url,
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": "TradingBotWatchdog/1.0"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return 200 <= resp.status < 300
        except urllib.error.HTTPError as exc:
            logger.error("Discord webhook HTTP %s: %s", exc.code, exc.read()[:200])
        except Exception as exc:
            logger.error("Discord webhook failed: %s", exc)
        return False
