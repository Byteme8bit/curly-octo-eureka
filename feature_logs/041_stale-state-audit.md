# 041 · fix(state): stale-state-on-disk audit + regression tests

**Status:** complete

## What changed
### `bot/paper_broker.py`
- Added `_parse_iso()` helper (shared with `from_dict`)
- `RiskState.from_dict()` now clears `paused_until` when the timestamp is in
  the past, so the bot never loads into an un-needed paused state
- Added `import logging` for the DEBUG log on prune

### `tests/test_watchdog_state.py`
- `test_load_drops_expired_wallclock_timestamps` — regression for 24h cutoff:
  valid wall-clock timestamps older than `max_age_sec=86400` must be dropped
  from `error_timestamps`, `watchdog_error_timestamps`, `seen_error_keys`,
  and `error_pin_windows` on load

### `tests/test_paper_state_stale.py` (new)
- `test_risk_state_clears_expired_paused_until` — core regression
- `test_risk_state_keeps_future_paused_until` — future pause preserved
- `test_risk_state_handles_missing_paused_until` — no crash on missing field
- `test_paper_state_stale_fixture` — end-to-end: load a stale JSON fixture
  and assert `paused_until` is cleared
- `test_pin_tracker_loads_clean` — documents `.discord_pins.json` has no TTL
  fields; all IDs are preserved
- `test_pin_tracker_ignores_wrong_channel` — mismatched channel drops IDs

## Audit summary
| File | TTL fields | Load-time prune? | Fix needed |
|------|-----------|-----------------|------------|
| `.auditor_state.json` | `expires_at` on proposals | ✓ (PR #8/#9) | — done |
| `.watchdog_state.json` | epoch timestamps | ✓ (already) | test added |
| `.paper_state.json` | `paused_until` ISO ts | ✗ | fixed here |
| `.discord_pins.json` | none | n/a | test documents it |

## Verification
```
pytest tests/test_paper_state_stale.py tests/test_watchdog_state.py -v
```
