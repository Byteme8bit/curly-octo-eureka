# Feature 038 — fix(stale-state): prune expired `paused_until` on load

## Status
completed

## Problem
`RiskState.from_dict()` loaded `paused_until` verbatim from disk without
checking whether the timestamp had already passed.  If the bot crashed
mid-hibernate, the next restart would read the stale expiry and remain paused
indefinitely — even hours or days after the window closed.

## Fix
Added `_prune_paused_until(value)` helper in `bot/paper_broker.py`.
On load it parses the ISO string; if the timestamp is in the past (or
unparseable), it returns `(None, True)`.  `RiskState.from_dict()` uses the
cleared value and also resets `hibernate_alert_sent = False` — mirroring what
`RiskManager.is_paused()` does at runtime when it self-clears the flag.

## Files changed
- `bot/paper_broker.py` — added `_prune_paused_until`, updated `RiskState.from_dict()`
- `tests/test_paper_state_stale.py` — new regression test module (12 tests)

## Tests
```
pytest tests/test_paper_state_stale.py -v
```
