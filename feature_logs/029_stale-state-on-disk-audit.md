# 029 — Stale-state-on-disk audit: .paper_state.json & .watchdog_state.json

**Requested:** 2026-05-31 (BACKLOG: "Detect other stale-state-on-disk patterns")
**Status:** awaiting verification — pytest pending

## Background

PR #8/#9 fixed `.auditor_state.json`: expired proposals were loaded from disk
and surfaced in the chat/status command after restarts. The same audit was owed
to the other three persistent state files.

## Audit results

| File | TTL fields | Pre-existing pruning | Action taken |
|------|-----------|---------------------|--------------|
| `.watchdog_state.json` | `error_timestamps`, `watchdog_error_timestamps`, `error_pin_windows`, `seen_error_keys` | ✅ `_clean_walltimes` / `_clean_wallmap` in `load()` | Added regression test for 24h TTL |
| `.paper_state.json` | `paused_until`, `hour_window_start` + `trades_this_hour` | ❌ only self-healed at runtime | **Fixed: prune at load time** |
| `.discord_pins.json` | None — stores Discord message IDs only | n/a | Documented; no code change needed |

## Problem: `.paper_state.json` (`RiskState.from_dict`)

Two fields were loaded verbatim without checking whether their window had
already elapsed:

1. **`paused_until`** — if the bot crashed during a drawdown hibernate and
   restarted hours later, `is_paused()` would return `True` for the duration
   of the first tick (until `_save()` cleared it). In most flows this is
   harmless because `_roll_hour_window()` runs before `can_trade_now()`, but
   it produced a window of spurious "HIBERNATING" log output and delayed the
   first trade approval.

2. **`hour_window_start` + `trades_this_hour`** — if the state file had
   `trades_this_hour: 5` from a window that opened 3 hours ago, the bot
   would start with 5 trades already counted against the hourly limit.
   `_roll_hour_window()` in `update_portfolio()` self-heals this, but again
   only after the first tick, leaving a window where `can_trade_now()` could
   incorrectly block trades.

## Fix: `bot/paper_broker.py` — `RiskState.from_dict()`

Prune at load time (defence-in-depth, same pattern as auditor state):

- **`paused_until`**: parse as ISO datetime; clear if `now >= until`.
  Malformed strings are also cleared.
- **`hour_window_start` / `trades_this_hour`**: if the window start is ≥ 1h
  ago, reset both to `None` / `0`. Malformed strings trigger the same reset.

No log entry is emitted (the fields are silent self-healed state, not
proposals the user created).

## Tests added

### `tests/test_watchdog_state.py`
- `test_load_prunes_24h_old_error_timestamps` — confirms that valid wall-clock
  timestamps older than 86400s are removed from `error_timestamps`,
  `watchdog_error_timestamps`, and `seen_error_keys` on load.

### `tests/test_paper_portfolio.py` — `TestRiskStateStaleStatePruning`
- `test_expired_paused_until_is_cleared_on_load`
- `test_future_paused_until_is_preserved_on_load`
- `test_stale_hour_window_resets_trade_counter`
- `test_active_hour_window_preserves_trade_counter`
- `test_malformed_paused_until_is_cleared`
- `test_malformed_hour_window_resets_counter`
- `test_none_paused_until_stays_none`
- `test_discord_pins_has_no_ttl_fields` — documents that `.discord_pins.json`
  has no TTL-based fields and requires no pruning logic.

## Files changed

- `bot/paper_broker.py` — `RiskState.from_dict()` stale-TTL pruning
- `tests/test_paper_portfolio.py` — 8 new tests
- `tests/test_watchdog_state.py` — 1 new test
- `BACKLOG.md` — top "Now" item marked `[x]`
- `feature_logs/029_stale-state-on-disk-audit.md` — this file

## Verification

```bash
python3 -m pytest tests/test_paper_portfolio.py tests/test_watchdog_state.py -v
python3 -m pytest  # full suite
```
