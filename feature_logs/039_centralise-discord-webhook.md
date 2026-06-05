# 039 — Centralise Discord webhook POST helper

**Requested:** 2026-06-05 (automation cycle)
**Status:** complete

## Request

Both `scripts/monitor_kraken_changes.py` and `scripts/post_discord_alert.py`
reimplemented the same urllib JSON-POST.  Extract to a single shared module
and give both scripts a one-liner.

## Actions taken

### New: `bot/notifications/__init__.py` + `bot/notifications/discord_webhook.py`

`post_webhook(webhook, *, content, username, timeout)` — handles:
- Content truncation at `DISCORD_HARD_LIMIT - SAFETY_HEADROOM` chars
- urllib POST with `Content-Type: application/json`
- Returns `0` on success, `2` on HTTP ≥ 300 or any network error
- Prints errors to `sys.stderr` rather than raising

### `scripts/post_discord_alert.py`

The former 25-line `post()` function is now a 2-line wrapper that formats a
`**title**\nbody` string and delegates to `post_webhook()`.

### `scripts/monitor_kraken_changes.py`

- Removed `urllib.request` import (no longer needed directly)
- Added `from bot.notifications.discord_webhook import post_webhook`
- The 30-line `post_discord()` function now delegates to `post_webhook()` for
  the actual HTTP call; content assembly is unchanged

### `tests/test_discord_webhook.py`

Five new unit tests covering: success (HTTP 204), HTTP error (403), network
error (OSError), long-content truncation, and username passthrough.

## Verification

```
python3 -m pytest tests/test_discord_webhook.py -v
```
Expected: 5 tests pass.
