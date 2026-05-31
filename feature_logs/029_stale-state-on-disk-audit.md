# 029 — Stale-state-on-disk audit (this branch)

**Requested:** 2026-05-31 (BACKLOG "Now" item)
**Status:** complete

## Request
Audit `.paper_state.json`, `.watchdog_state.json`, `.discord_pins.json` for
TTL-based fields that `load()` doesn't prune. Add regression tests per file.

## Actions taken

### `watchdog/state.py`
- Added `_clean_recent_errors()`: drops `recent_errors` records whose `at`
  timestamp (format `YYYY-MM-DD HH:MM:SS TZAbbr`) is older than 24 h.
  Records with unparseable timestamps are kept defensively.
- Wired into `WatchdogState.load()` for the `recent_errors` field.
  (Other timestamp collections — `error_timestamps`, `seen_error_keys`,
  `error_pin_windows` — were already cleaned via `_clean_walltimes`/
  `_clean_wallmap`.)

### `bot/paper_broker.py`
- `RiskState.from_dict()` now prunes two stale TTL fields on load:
  - `paused_until`: cleared when the pause window has already elapsed so a
    restarted bot doesn't start in spurious HIBERNATING state.
  - `hour_window_start` / `trades_this_hour`: reset to `None` / `0` when
    the recorded window started more than 1 h ago, so the rate limiter
    doesn't carry a stale count across restarts.

### `.discord_pins.json` (PinTracker)
- Contains only message IDs with no wall-clock TTL fields; no pruning needed.

### Tests
- `tests/test_risk_state.py` (new, 10 tests): covers expired/future
  `paused_until`, expired/fresh `hour_window_start`, unparseable values,
  and None/empty inputs.
- `tests/test_watchdog_state.py` (2 new tests): covers 24 h TTL pruning
  of `recent_errors` and the defensive keep-on-unparseable-at path.

## Verification
288 passed (was 274). All new tests green locally.
