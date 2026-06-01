# 033 — Centralise Discord webhook posting

**Requested:** BACKLOG "Soon" — both `scripts/monitor_kraken_changes.py` and
`scripts/post_discord_alert.py` re-implement the same urllib JSON-POST. Extract
to `bot/notifications/discord_webhook.py`.
**Status:** complete — 317 passed

## Problem

Two scripts contained identical copy-pasted urllib boilerplate for posting to a
Discord webhook:
- `scripts/post_discord_alert.py` — ~15 lines of urllib + truncation logic
- `scripts/monitor_kraken_changes.py` — ~20 lines of the same

Any bug fix or enhancement (e.g. username override, retry, different truncation
marker) had to be applied in two places.

## Actions taken

### New: `bot/notifications/__init__.py` + `bot/notifications/discord_webhook.py`

- `post_webhook(webhook, content, *, username, timeout) -> None` — single
  implementation of the urllib POST with truncation, `Content-Type` header,
  and HTTP status checking.
- Raises `DiscordWebhookError` (a `RuntimeError` subclass) on failure so
  callers can catch specifically without a bare `except`.
- Auto-truncates to `DISCORD_HARD_LIMIT - SAFETY_HEADROOM` (1900 chars).

### `scripts/post_discord_alert.py`

`post()` now calls `post_webhook` and catches `DiscordWebhookError`. The
public API (`main()`, exit codes 0/2/3) is unchanged.

### `scripts/monitor_kraken_changes.py`

`post_discord()` now calls `post_webhook` and catches `DiscordWebhookError`.
Behaviour and output are identical.

Both scripts add the workspace root to `sys.path` at the top so they can be
run directly via `python scripts/…` without a package install.

## Notes
- No behavioural changes to either script — only the posting plumbing moved.
- `bot/notifications/discord_webhook.py` is pure stdlib; no new runtime
  dependencies.
