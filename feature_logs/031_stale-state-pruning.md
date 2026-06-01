# 031 — Stale TTL state pruning on load

**Requested:** BACKLOG "Now" — audit persistent state files for stale TTL fields
**Status:** complete — 317 passed (12 new regression tests)

## Problem

Two persistent state files contained TTL-based fields that could outlive their
intended scope when the bot is restarted:

- **`.paper_state.json` (`RiskState`):**
  - `paused_until` — hibernate expiry timestamp. If the bot was paused and then
    restarted after the pause expired, `is_paused()` would still read the stale
    value on the first tick before clearing it.
  - `hour_window_start` + `trades_this_hour` — rate-limit window. An hour window
    from a previous session would continue constraining the new session until the
    3600-second timeout fired organically.

- **`.watchdog_state.json` (`WatchdogState`):**
  - `seen_diagnostics` — grows without bound (unlike `seen_receipts` which already
    has a `max_retain=500` cap). A long-running bot accumulates thousands of
    entries, slowing JSON serialisation and inflating the state file.

## Actions taken

### `bot/paper_broker.py`
- Added `PaperBroker._prune_stale_risk_fields(risk: RiskState) -> bool` static
  method that:
  - Clears `paused_until` (and `hibernate_alert_sent`) when the datetime is in
    the past or unparseable.
  - Resets `hour_window_start` and `trades_this_hour` when the window is ≥3600 s
    old or unparseable.
  - Returns `True` if any field changed (so the caller can persist immediately).
- `_load_or_create` now calls `_prune_stale_risk_fields` on every disk load and
  saves if any field was pruned.

### `watchdog/state.py`
- `WatchdogState.load`: `seen_diagnostics` is now capped to the last 500 entries
  (`[-500:]`) on load.
- `mark_diagnostic_seen`: cap enforced at runtime too (matches `mark_receipt_seen`
  pattern).

## Tests added (`tests/test_stale_state.py`)

12 new regression tests across both state files:

| Test | Asserts |
|---|---|
| `test_paper_state_expired_paused_until_is_cleared` | expired `paused_until` cleared |
| `test_paper_state_future_paused_until_is_kept` | future `paused_until` preserved |
| `test_paper_state_invalid_paused_until_is_cleared` | bad timestamp treated as expired |
| `test_paper_state_expired_hour_window_resets_trade_counter` | stale window resets counter |
| `test_paper_state_recent_hour_window_is_kept` | fresh window and counter preserved |
| `test_paper_state_both_stale_fields_cleared_together` | both expired simultaneously |
| `test_prune_stale_risk_fields_returns_false_when_nothing_to_do` | no-op returns False |
| `test_prune_stale_risk_fields_returns_true_on_any_change` | changed returns True |
| `test_watchdog_seen_diagnostics_capped_at_500_on_load` | 600-entry list → 500 on load |
| `test_watchdog_seen_diagnostics_under_500_unchanged_on_load` | short list unchanged |
| `test_watchdog_mark_diagnostic_seen_caps_at_runtime` | runtime cap enforced |
| `test_watchdog_mark_diagnostic_seen_dedup` | duplicate returns False, no growth |

## Notes
- `.discord_pins.json` (`PinTracker`) already enforces `max_retain` in every
  write path (`register`, `reconcile`). No TTL-based fields exist. No change needed.
