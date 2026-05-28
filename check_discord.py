"""Verify Discord bot token, channel access, and webhook."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

from dotenv import load_dotenv

from bot.discord_bot import DISCORD_API, DISCORD_USER_AGENT
from config import load_settings

load_dotenv()


def _request(method: str, url: str, token: str, payload: dict | None = None):
    headers = {
        "Authorization": f"Bot {token}",
        "User-Agent": DISCORD_USER_AGENT,
    }
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8")
        return resp.status, json.loads(raw) if raw else None


def _webhook_test(url: str) -> tuple[bool, str]:
    data = json.dumps({"content": "Webhook test from eth-trading-bot (safe to ignore)"}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": DISCORD_USER_AGENT},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return True, f"OK (HTTP {resp.status})"
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return False, f"HTTP {e.code} — {body[:300]}"
    except Exception as e:
        return False, str(e)


def main() -> int:
    settings = load_settings()
    token = settings.discord_bot_token.strip()
    channel = settings.discord_channel_id.strip()
    webhook = settings.discord_webhook.strip()

    print("Discord connectivity check\n" + "=" * 40)

    if not token:
        print("FAIL  DISCORD_BOT_TOKEN is empty")
        return 1

    # 1. Bot identity
    try:
        status, me = _request("GET", f"{DISCORD_API}/users/@me", token)
        print(f"OK    Bot token valid — logged in as {me.get('username')} ({me.get('id')})")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"FAIL  Bot token invalid — HTTP {e.code}: {body[:300]}")
        print("      → Reset token in Developer Portal → Bot → Reset Token, update .env")
        return 1

    if not channel:
        print("FAIL  DISCORD_CHANNEL_ID is empty")
        return 1

    # 2. Channel access
    try:
        status, ch = _request("GET", f"{DISCORD_API}/channels/{channel}", token)
        print(f"OK    Channel access — #{ch.get('name', '?')} ({channel})")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"FAIL  Cannot access channel {channel} — HTTP {e.code}: {body[:300]}")
        print("      → Re-invite bot to your server with View Channel + Read History + Send Messages")
        print("      → Confirm DISCORD_CHANNEL_ID matches the control channel")
        return 1

    # 3. Read messages (command listener)
    try:
        _request("GET", f"{DISCORD_API}/channels/{channel}/messages?limit=1", token)
        print("OK    Can read message history (commands will work)")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"FAIL  Cannot read messages — HTTP {e.code}: {body[:300]}")
        print("      → Enable Message Content Intent in Developer Portal → Bot")
        print("      → Re-invite bot with Read Message History permission")
        return 1

    # 4. Post via bot
    try:
        _request(
            "POST",
            f"{DISCORD_API}/channels/{channel}/messages",
            token,
            {"content": "Bot post test from eth-trading-bot (safe to ignore)"},
        )
        print("OK    Bot can post messages")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"FAIL  Bot cannot post — HTTP {e.code}: {body[:300]}")
        print("      → Give bot Send Messages permission in channel/server settings")
        return 1

    # 5. Webhook (optional)
    if webhook:
        ok, msg = _webhook_test(webhook)
        label = "OK   " if ok else "WARN "
        print(f"{label} Webhook: {msg}")
        if not ok:
            print("      → Regenerate webhook in channel → Integrations → Webhooks → Copy URL")
            print("      → Bot posting still works without webhook")
    else:
        print("SKIP  No DISCORD_WEBHOOK set (bot token posting is enough)")

    print("\nAll required checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
