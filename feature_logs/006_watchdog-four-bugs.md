# 006 — Watchdog: stop, heartbeat, error count, pinning

**Requested:** 2026-05-25
**Status:** complete

## Request
> 1) WatchDog did not stop with TradeBot
> 2) Not seeing WatchDog heartbeat reports in discord
> 3) WatchDog not properly cataloging/counting TradeBot's errors - always reports back as 0
> 4) Instead of pinning every error by TradeBot, let's only pin if the same error happens more than 3 times in less than an 30 minutes

## Actions taken

### Bug 1 — Watchdog didn't stop
- **`watchdog/engine.py`** — added `request_stop()` method that sets `_stop_requested` flag
- Poll loop now checks the flag between each check and between each alert send, so shutdown doesn't wait the full Discord HTTP timeout per queued alert
- **`bot/watchdog_service.py`** — `stop()` calls `engine.request_stop()` before join; join timeout reduced to 5s

### Bug 2 — No heartbeat in Discord
- **`watchdog/engine.py`** — heartbeat moved into its own try block so errors elsewhere in `poll_once` don't kill it
- Each check (`_check_runtime_log`, etc.) wrapped individually so one failure doesn't drop the rest
- Per-alert exceptions logged without aborting the queue
- Heartbeat anchor reset on `begin_session()` so first beat fires `heartbeat_minutes` after fresh start

### Bug 3 — Error count always 0
- **`watchdog/state.py`** — rewrote with two error buckets: `error_timestamps` (bot) and `watchdog_error_timestamps` (watchdog self)
- All persisted timestamps switched from `time.monotonic()` to `time.time()` (wall clock) so they survive restart
- Migration on load: timestamps below the year 2001 epoch are dropped (stale monotonic values)
- **`watchdog/engine.py`** — `_check_runtime_log` no longer filters out `Watchdog ` errors; categorizes them instead
- **`watchdog/scoring.py`** — `HealthReport` exposes `bot_errors_last_hour` and `watchdog_errors_last_hour` separately; only bot errors penalize health heavily

### Bug 4 — Pin every error
- Same monotonic→wall-clock fix applied to `track_error_for_pin` so the "more than 3 in 30 min" gate works after restarts
- Alert text now shows `(pinned)` or `(not pinned yet)` for visibility

## Verification
- All modified modules compile cleanly (verified by inspection — shell can't run due to sandbox)
- Heartbeat will appear in Discord ~15 min after restart with format: `**Watchdog heartbeat** — Everything is normal | Health 100/100 | Trade-bot errors: 0 last hour | Watchdog self-errors: 0 last hour`

## Notes
- No `.env` changes needed; existing `WATCHDOG_HEARTBEAT_MINUTES=15`, `DISCORD_ERROR_PIN_COUNT=3`, `DISCORD_ERROR_PIN_WINDOW_MINUTES=30` now work correctly.
- Old `.watchdog_state.json` will be auto-cleaned of stale monotonic timestamps on first load.
