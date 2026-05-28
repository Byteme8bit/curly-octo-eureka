# 014 — Reset clears error counts + all Discord pins

**Requested:** 2026-05-25
**Status:** awaiting verification — pytest pending

## Request
> Does my "reset" command also clear out that sessions error count for both bots? If not, it should.
>
> Also, "reset" or "TradeBot -reset" should also clear all pinned messages as well as resetting the paper status

## Prior behavior
- **WatchDog error counts** — already cleared via `watchdog.reset()` → `WatchdogState.reset_session()` (`error_timestamps`, `watchdog_error_timestamps`, `error_pin_windows`, `recent_errors`, etc.).
- **TradeBot error counts** — **not** cleared. In-memory `_error_last_posted` and `_error_pin_occurrences` on `DiscordBot` survived reset, so dedup/pin-burst logic still remembered old errors.
- **Discord pins** — reset called `clear_recent_messages(exclude_pinned=True)`, which **skipped** pinned messages. Old startup pins, error pins, and trade pins remained.

## Actions taken

### `bot/discord_bot.py`
- `clear_session_errors()` — clears TradeBot in-memory error dedup + pin-burst counters.
- `clear_all_pins()` — fetches live channel pins, unpins + deletes every **bot-authored** pin, then `PinTracker.clear_all()`.
- `reset_discord_channel()` — orchestrates pins → error counters → `clear_recent_messages(exclude_pinned=False)`.
- Updated help text: `TradeBot -reset` now documents full cleanup.

### `bot/pin_tracker.py`
- `clear_all()` — drops all tracked pin ids + startup pin id.

### `bot/engine.py` — `reset` handler
1. Reset paper state + circuit breaker + engine session vars.
2. `watchdog.reset(silent=True)` — clears WatchDog error counters **without** posting a stray chat message.
3. `discord.reset_discord_channel()` — pins + messages + TradeBot error counters.
4. `post_startup_pin()` — single fresh startup pin in a clean channel.
5. Reply mentions pins cleared, messages deleted, and both bots' error counters reset.

### `bot/watchdog_service.py`
- `reset(silent=False)` — when `silent=True` (TradeBot reset path), skips the watchdog reset alert so the channel stays clean.

### Tests (`tests/test_discord_commands.py`)
- `TestResetSessionCleanup` — 3 tests: error counter clear, pin unpin/delete, full `reset_discord_channel` orchestration.

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_discord_commands.py -v
.\.venv\Scripts\python.exe -m pytest tests\test_watchdog_state.py::test_reset_session_clears_both_buckets -v
```

Live Discord smoke test:
1. Pin a few bot messages (trigger an error or trade alert).
2. Send `TradeBot -reset`.
3. Confirm: all old pins gone, one new startup pin, heartbeat shows **0** errors.
