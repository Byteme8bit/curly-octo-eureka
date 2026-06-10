# 044 — Discord chatter reduction (whale alerts)

**Requested:** 2026-06-10
**Status:** awaiting verification — pytest pending
**Branch:** `feature/044-discord-chatter-reduction`
**Request-ID:** 044

## Request

Reduce Discord noise — especially routine whale movement alerts. Bot should
stay aware (whale watch + follow) but only post **significant** messages:
trade narration, WatchDog health/errors, Auditor actions. Whale detections
log to file instead.

## Actions taken

- `WHALE_WATCH_DISCORD_ALERTS` (default `0`) — gates Discord posts from
  `_maybe_whale_watch`; watch + state persistence + follow unchanged.
- `WHALE_WATCH_LOG_FILE` (default `logs/whale_watch.log`) — append-only quiet
  log via `append_whale_event_log` in `bot/whale_watch.py`.
- Whale-follow **trade** posts (`post_important`, source TradeBot) kept.
- `.env.example` and local `.env` updated (`WHALE_WATCH_DISCORD_ALERTS=0`).
- `tests/test_whale_watch_discord.py` — config default, file log, engine gating.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_whale_watch_discord.py tests/test_whale_watch.py -q
```

Restart TradeBot after deploy so singleton picks up `.env` change.
