"""Tiny CLI to post an alert to the TradeBot Discord channel.

Used by the 8-hour maintenance automation (see automation/maintenance_prompt.md)
so the cloud agent can tell you what it did and why without you having to
go look at the PR queue. Reads ``DISCORD_WEBHOOK`` from the environment.

Usage:
    python scripts/post_discord_alert.py \
        --title "Auto-maintenance" \
        --body  "Opened draft PR #42: fix stale fee cache warning.

WHY: runtime.log showed 'Could not fetch trading fees' repeating every 5m
since the last restart. Auth fallback path was logging at WARNING but
should be DEBUG since it is expected. PR replaces the log level.

Link: <https://github.com/Byteme8bit/curly-octo-eureka/pull/42>"

Exit code: 0 on success, 2 on Discord error, 3 on missing webhook.
The script never blocks the caller for more than 10 seconds.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request


DISCORD_HARD_LIMIT = 2000  # Discord rejects messages longer than this
SAFETY_HEADROOM = 100      # leave room for the "(truncated)" marker


def post(webhook: str, *, title: str, body: str, username: str) -> int:
    content = f"**{title}**\n{body}"
    if len(content) > DISCORD_HARD_LIMIT - SAFETY_HEADROOM:
        cut = DISCORD_HARD_LIMIT - SAFETY_HEADROOM
        content = content[:cut] + "\n…(truncated — see PR for full detail)"
    payload = json.dumps({"username": username, "content": content}).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status >= 300:
                print(f"ERROR: Discord returned HTTP {resp.status}", file=sys.stderr)
                return 2
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: Discord post failed: {exc}", file=sys.stderr)
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True, help="Bold header (one line).")
    parser.add_argument(
        "--body",
        required=True,
        help="Message body. Markdown supported. Pass '-' to read from stdin.",
    )
    parser.add_argument(
        "--username",
        default="Auto-Maintenance",
        help="Webhook username override shown in Discord.",
    )
    args = parser.parse_args()

    webhook = (os.environ.get("DISCORD_WEBHOOK") or "").strip()
    if not webhook:
        print(
            "ERROR: DISCORD_WEBHOOK env var not set. In Cursor automations, "
            "add it under Secrets in the automation config.",
            file=sys.stderr,
        )
        return 3

    body = sys.stdin.read() if args.body == "-" else args.body
    return post(webhook, title=args.title, body=body, username=args.username)


if __name__ == "__main__":
    sys.exit(main())
