# Feature 029 — Stale-state-on-disk TTL pruning

**Status:** complete

## Problem

Three persistent state files could wake up with expired time-bounded data:

| File | Field | Issue |
|---|---|---|
| `.watchdog_state.json` | `recent_errors` | No TTL — stale error records persisted forever |
| `.paper_state.json` → `risk` | `paused_until` | Expired hibernate windows kept the bot paused after restart |
| `.paper_state.json` → `risk` | `hour_window_start` / `trades_this_hour` | Stale window carried an incorrect hourly trade count into the new session |

## Changes

### `watchdog/state.py`
- Added `_clean_recent_errors()` helper: drops records whose `"_ts"` field (unix epoch)
  is more than 24 hours old. Records without `"_ts"` (old builds) are kept for
  backward compatibility.
- `WatchdogState.load()`: passes `recent_errors` through `_clean_recent_errors()`.
- `WatchdogState.append_error()`: injects `"_ts": time.time()` into every record
  (unless the caller already provides one).

### `bot/paper_broker.py`
- `RiskState.from_dict()`: prunes `paused_until` (and resets `hibernate_alert_sent`)
  when the timestamp is ≤ now.
- `RiskState.from_dict()`: resets `hour_window_start` to `None` and
  `trades_this_hour` to `0` when the window start is ≥ 1 hour ago.
- Malformed / unparseable ISO strings for either field are also cleared.

## Tests added (14 new)

| Test file | Tests |
|---|---|
| `tests/test_watchdog_state.py` | `test_append_error_stamps_ts`, `test_append_error_preserves_existing_ts`, `test_load_prunes_stale_recent_errors`, `test_load_keeps_recent_errors_without_ts` |
| `tests/test_risk_state_load.py` | `test_from_dict_clears_expired_paused_until`, `test_from_dict_keeps_future_paused_until`, `test_from_dict_clears_malformed_paused_until`, `test_from_dict_resets_stale_hour_window`, `test_from_dict_keeps_recent_hour_window`, `test_from_dict_resets_malformed_hour_window`, `test_from_dict_none_data_returns_defaults` |

## Verification

```
pytest tests/test_watchdog_state.py tests/test_risk_state_load.py -v
# 13 passed
pytest  # 288 passed
```
