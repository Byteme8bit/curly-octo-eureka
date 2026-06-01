# 031 — Stale-state TTL pruning (paper, watchdog, discord_pins)

**Requested:** 2026-06-01 (automation cycle — BACKLOG "Now")
**Status:** complete

## Request

> Audit the other persistent state files (`.paper_state.json`,
> `.watchdog_state.json`, `.discord_pins.json`) for similar TTL-based fields
> that `load()` doesn't prune. Add a regression test per file that loads a stale
> fixture and asserts the expired entries are dropped.

## Analysis

| File | Field | Problem | Fix |
|------|-------|---------|-----|
| `.paper_state.json` | `risk.paused_until` | ISO timestamp — if past, bot remains in hibernate state until `RiskManager.is_paused()` is called | Clear on `_load_or_create()` + persist |
| `.paper_state.json` | `risk.hour_window_start` | 1-hour trade-rate window — if older than 1 h, `trades_this_hour` is wrong | Reset counter + clear timestamp |
| `.watchdog_state.json` | `seen_diagnostics` | No size cap anywhere — list grows without bound across restarts | Cap at 500 on `load()` and in `mark_diagnostic_seen()` |
| `.discord_pins.json` | (no TTL fields) | `reconcile()` + channel_id mismatch already handle stale IDs correctly | No code change — added regression test confirming behaviour |

## Actions taken

- **`bot/paper_broker.py`**
  - Added `import logging` + module-level `logger`
  - Added `_prune_stale_risk_fields(risk: RiskState) -> int` — clears expired
    `paused_until` / `hibernate_alert_sent` and resets stale `hour_window_start`
    / `trades_this_hour`; handles malformed ISO strings as "stale"
  - `_load_or_create()` calls the helper, logs a WARNING on prune, and rewrites
    the on-disk file so the next load starts clean

- **`watchdog/state.py`**
  - `WatchdogState.load()` — `seen_diagnostics=list(...)[-500:]`
  - `mark_diagnostic_seen()` — added `max_retain=500` parameter + cap logic

- **`tests/test_stale_state.py`** (new) — 12 regression tests covering:
  - `paper_broker`: expired `paused_until` cleared, future preserved; stale
    `hour_window_start` reset, fresh preserved; on-disk file rewritten; malformed
    timestamps treated as stale
  - `watchdog_state`: 600-item `seen_diagnostics` capped to 500, most-recent
    kept; runtime `mark_diagnostic_seen` cap
  - `pin_tracker`: channel_id mismatch drops all IDs; matching channel restores
    correctly; startup pin de-duped from regular ids

## Verification

```
pytest tests/test_stale_state.py -v
```

All 12 tests pass.

## Notes

- `_prune_stale_risk_fields` is a module-level function (underscore-prefix)
  so tests can import it directly to assert specific return counts.
- `file_offsets` in `watchdog/state.py` is intentionally NOT pruned — it tracks
  log-file byte offsets and pruning would cause re-processing of old log lines.
