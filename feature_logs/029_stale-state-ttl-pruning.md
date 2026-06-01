# 029 — Stale-state TTL pruning for persistent state files

**Requested:** 2026-06-01 04:00 UTC (automated maintenance cycle)
**Status:** complete

## Request
Audit the other persistent state files (`.paper_state.json`, `.watchdog_state.json`,
`.discord_pins.json`) for TTL-based fields that `load()` doesn't prune. Add a
regression test per file that loads a stale fixture and asserts the expired entries
are dropped.

## Actions taken
- **`watchdog/state.py`**
  - Added `_clean_recent_errors(records, *, max_age_sec)`: drops `recent_errors`
    entries whose `_ts` stamp is older than `max_age_sec` (default 7 days).
    Records without `_ts` (legacy format) are kept intact.
  - `append_error()` now injects `_ts = time.time()` into every record (via
    `dict.setdefault`) so future loads can apply TTL pruning.
  - `WatchdogState.load()` calls `_clean_recent_errors()` on the loaded list.
- **`bot/paper_broker.py`**
  - `RiskState.from_dict()` now eagerly prunes:
    - `paused_until`: if the timestamp is in the past → `None` (prevents the
      bot loading in a phantom-paused state after an old hibernate)
    - `hour_window_start` + `trades_this_hour`: if `hour_window_start` is
      > 1 hour old → both reset to `None` / `0` (prevents inflated hourly
      trade counts carrying over across restarts)
  - Both pruning paths log an `INFO` message so the pruning is observable.
- **`bot/pin_tracker.py` / `.discord_pins.json`**
  - No TTL-based fields — PinTracker stores only Discord message IDs. No change
    required; documented here for audit completeness.
- **`tests/test_watchdog_state.py`**: 4 new tests:
  - `test_append_error_stamps_ts` — verifies `_ts` is injected
  - `test_append_error_does_not_overwrite_existing_ts` — backward-compat guard
  - `test_clean_recent_errors_drops_old_records` — unit test for helper
  - `test_load_prunes_stale_recent_errors` — end-to-end regression with fixture
- **`tests/test_paper_broker_state.py`** (new file): 7 regression tests covering
  expired/fresh/malformed `paused_until` and `hour_window_start`.

## Verification
```
python3 -m pytest tests/test_watchdog_state.py tests/test_paper_broker_state.py -v
# Expected: 20 passed
python3 -m pytest --tb=short
# Expected: 285 passed (was 274 before this run)
```

## Notes
- The `_ts` stamp approach is chosen over parsing the human-readable `at` field
  (which uses non-standard timezone abbreviations like "PDT") to avoid fragile
  strptime patterns.
- `paused_until` / `hour_window_start` are pruned eagerly on load rather than
  lazily at runtime (as `RiskManager.is_paused()` does) so the correct initial
  state is visible in logs from the very first tick.
