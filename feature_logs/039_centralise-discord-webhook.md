# 039 · refactor(notifications): centralise Discord webhook posting

**Status:** complete

## What changed
- **New**: `bot/notifications/__init__.py` — package init
- **New**: `bot/notifications/discord_webhook.py` — `post_webhook()` +
  `post_alert()` helpers (shared urllib JSON-POST logic)
- **Refactored**: `scripts/post_discord_alert.py` — removed duplicated
  urllib block; calls `post_alert()` instead
- **Refactored**: `scripts/monitor_kraken_changes.py` — removed duplicated
  urllib block; `post_discord()` calls `post_webhook()` instead
- **New**: `tests/test_discord_webhook.py` — 8 tests covering success, empty
  webhook, HTTP error, network error, title/body formatting, truncation

## Why
Both scripts reimplemented the same urllib JSON-POST.  One shared module
keeps the error handling and truncation logic in one place.

## Verification
```
pytest tests/test_discord_webhook.py -v
```
