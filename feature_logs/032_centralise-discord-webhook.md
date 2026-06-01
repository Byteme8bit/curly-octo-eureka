# 032 — Centralise Discord webhook posting

**Requested:** 2026-06-01 (backlog item "Soon")
**Status:** complete

## Request

Both `scripts/monitor_kraken_changes.py` and `scripts/post_discord_alert.py`
reimplemented the same urllib JSON-POST to Discord. Extract to
`bot/notifications/discord_webhook.py` and give both scripts a one-liner.

## Actions taken

- **New file** `bot/notifications/__init__.py` — package stub.
- **New file** `bot/notifications/discord_webhook.py` — `post_webhook(webhook, content, *, username, timeout)` function.
  - Strips leading/trailing whitespace from the URL; returns False on empty URL.
  - Truncates content to fit Discord's 2000-char hard limit with a `…(truncated)` suffix.
  - Returns `bool`; logs warnings on HTTP error or network exception.
- **Modified** `scripts/post_discord_alert.py` — removed inline urllib POST; `post()` now calls `post_webhook()`.
- **Modified** `scripts/monitor_kraken_changes.py` — removed inline `urllib.request` import; `post_discord()` body replaced with a single `post_webhook()` call; `sys.path` insert added so the local `bot` package is importable when run as a script.
- **New file** `tests/test_discord_webhook.py` — 8 unit tests covering success, custom username, truncation, HTTP error, network exception, empty/whitespace URL.

## Verification

```
python3 -m pytest tests/test_discord_webhook.py -v
```

282 tests pass (274 baseline + 8 new).

## Notes

`monitor_kraken_changes.py` retained its inline `json` import (still used for
JSONL logging and baseline serialisation). Only the HTTP-POST code was removed.
