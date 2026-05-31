# 022 — Maintenance run 2026-05-31 (automated 4-hour cycle)

**Triggered:** 2026-05-31 04:01 UTC (cron — every 4 hours)
**Status:** complete

## Summary

Automated optimization cycle — no new user-requested features. All changes
address items from `BACKLOG.md` (Now / Soon buckets). Full test suite (259
tests) passes before and after; coverage threshold added to CI.

---

## Changes

### 1 — `.gitattributes` added (new file)

**Backlog:** "Add `.gitattributes` to normalise line endings."

Added `* text=auto eol=lf` plus explicit binary overrides for image/archive
formats. Eliminates the ~30 spurious `M` entries on Windows caused by
CRLF↔LF flapping on every commit.

### 2 — `bot/fee_engine.py` — log level fix

**Backlog:** "Audit log levels across `bot/`."

`_try_personalised_fees` and `_try_public_schedule` used `logger.warning()`
on success paths ("Fee source: PERSONALISED …" / "Fee source: PUBLIC …").
Success messages should be `INFO` (visible but not alarming). Changed both
to `logger.info()`. The failure fallback paths remain `WARNING` or `ERROR`.

Two tests in `tests/test_fee_engine.py` that captured `WARNING` to verify
these messages were updated to capture at `INFO` level.

### 3 — `docs/logging_conventions.md` added (new file)

**Backlog:** "Audit log levels … write it as a short policy in
`docs/logging_conventions.md`."

Documents the five-level convention (CRITICAL / ERROR / WARNING / INFO /
DEBUG), the decision heuristic, common mistakes, and a per-module sweep
status table. Serves as reference for future reviews.

### 4 — `watchdog/state.py` — cap `seen_diagnostics` list

**Backlog:** "Detect other stale-state-on-disk patterns."

`mark_diagnostic_seen()` had no retention cap, unlike `mark_receipt_seen`
which caps at 500. Over many days the list would grow unboundedly in RAM and
on disk. Fixed by adding `max_retain=500` trimming identical to the receipts
cap. The `load()` method also now slices to `[-500:]` on read so old state
files with oversized lists are corrected on the first startup.

### 5 — `pytest --cov` added to CI

**Backlog:** "Add a `pytest --cov` run to CI so coverage drops are visible."

- Added `pytest-cov>=5.0.0` to `requirements-dev.txt`.
- Updated `.github/workflows/test.yml` to run with
  `--cov=bot --cov=watchdog --cov-report=term-missing --cov-fail-under=45`.
- Threshold set to **45 %** (current actual: 45.64 %) as the ratchet
  baseline. Raise by 5 pp per quarter as new tests ship.

### 6 — `bot/preflight.py` — basis-point messages

**Backlog:** "Improve `pre-flight reject` messages."

The reject string now shows values in basis points instead of raw decimals:

```
Before: Pre-flight reject: net +0.0012 (gross +0.0052 - fees 0.0040 - slippage 0.0000) <= min 0.0005
After:  Pre-flight reject: net +12.0bps (gross +52.0bps - fees 40.0bps - slippage 0.0bps) <= min 5.0bps
```

`Pre-flight OK` similarly shows the net in bps.

---

## Files changed

| File | Type |
|---|---|
| `.gitattributes` | **new** |
| `docs/logging_conventions.md` | **new** |
| `feature_logs/022_maintenance-run-2026-05-31.md` | **new** |
| `bot/fee_engine.py` | modified |
| `bot/preflight.py` | modified |
| `watchdog/state.py` | modified |
| `tests/test_fee_engine.py` | modified |
| `requirements-dev.txt` | modified |
| `.github/workflows/test.yml` | modified |

## Backlog items now done

- [x] **Add `.gitattributes` to normalise line endings.**
- [x] **Audit log levels across `bot/`.** (fee_engine fixed; policy doc written)
- [x] **Improve `pre-flight reject` messages.** (basis points)
- [x] **Add a `pytest --cov` run to CI** (threshold 45 %, ratchet-up noted)

## Backlog items partially addressed

- **Detect other "stale-state-on-disk" patterns.** Fixed `seen_diagnostics`
  in `watchdog/state.py`. `WatchdogState` was already clean elsewhere
  (`_clean_walltimes`, `_clean_wallmap`). `RiskState` fields
  (`paused_until`, `circuit_breaker_at`) are self-healing via `RiskManager`
  on first tick — no fix needed. `PinTracker` has no TTL fields.
  Item can be closed.
