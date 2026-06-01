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
import os
import sys

# Allow running the script directly from the project root without installing the
# package — insert the workspace root onto sys.path if needed.
_ROOT = str(__import__("pathlib").Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from bot.notifications.discord_webhook import DiscordWebhookError, post_webhook


def post(webhook: str, *, title: str, body: str, username: str) -> int:
    content = f"**{title}**\n{body}"
    try:
        post_webhook(webhook, content, username=username)
    except DiscordWebhookError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
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
