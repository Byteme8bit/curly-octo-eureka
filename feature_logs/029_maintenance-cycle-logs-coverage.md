# 029 — Maintenance cycle: line-endings, log levels, stale-state prune, coverage CI

**Requested:** 2026-05-31 (scheduled 4h maintenance agent)
**Status:** complete

## Request

Automated maintenance cycle. Worked through the "Now" backlog items:
1. Add `.gitattributes` for CRLF normalisation.
2. Audit log levels + write `docs/logging_conventions.md`.
3. Detect stale-state-on-disk patterns (extends the #8/#9 auditor fix).
4. Add `pytest --cov` to CI.

## Actions taken

### 1. `.gitattributes`
- Created `.gitattributes` with `* text=auto eol=lf` plus explicit overrides
  for `.py`/`.md`/`.json`/`.yml` and binary format exclusions.
- Ran `git add --renormalize .` — no diffs produced (repo was already LF).
- Addresses the "~30 spurious M entries" on Windows dev machines.

### 2. Logging conventions + `fee_engine.py` fix
- `bot/fee_engine.py`: `_try_personalised_fees` and `_try_public_schedule`
  both logged `WARNING` on **successful** schedule load. Changed to `INFO`.
  Failures and fallbacks remain `WARNING`.
- Created `docs/logging_conventions.md` documenting the project-wide level
  policy: `WARNING` = degraded/fallback path; `INFO` = normal lifecycle event.
- Updated two tests in `tests/test_fee_engine.py` that were asserting
  `caplog.at_level("WARNING")` for the success messages (now capture at INFO).

### 3. `WatchdogState.recent_errors` TTL prune on load
- `watchdog/state.py`: added `_clean_recent_errors()` helper that parses the
  string `"YYYY-MM-DD HH:MM:SS TZ"` `at` field and drops records older than
  24h, matching the existing `_clean_walltimes`/`_clean_wallmap` pattern.
- Applied in `WatchdogState.load()` alongside all the other TTL cleanups.
- Records with unparseable timestamps are kept defensively.
- Added `test_load_prunes_stale_recent_errors` to `tests/test_watchdog_state.py`.

### 4. `pytest --cov` in CI
- Added `pytest-cov>=5.0.0` to `requirements-dev.txt`.
- Updated `.github/workflows/test.yml`: `pytest` now runs with
  `--cov=bot --cov=watchdog --cov-report=term-missing --cov-fail-under=45`.
  Current baseline ~46%; 45% floor gives a small regression buffer.

## Verification

```
pytest -v           # 260 passed, 0 failed
```

## Files changed

- **Added** `.gitattributes`
- **Added** `docs/logging_conventions.md`
- **Added** `feature_logs/029_maintenance-cycle-logs-coverage.md` (this file)
- **Modified** `bot/fee_engine.py` — WARNING→INFO for successful loads
- **Modified** `watchdog/state.py` — `_clean_recent_errors` + import datetime
- **Modified** `tests/test_fee_engine.py` — caplog level INFO fix
- **Modified** `tests/test_watchdog_state.py` — new TTL prune test
- **Modified** `requirements-dev.txt` — add pytest-cov
- **Modified** `.github/workflows/test.yml` — add coverage flags
