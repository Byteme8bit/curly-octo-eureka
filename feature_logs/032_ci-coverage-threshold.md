# 032 — CI coverage threshold (50%)

**Requested:** BACKLOG "Now" — pin a minimum coverage threshold now that
`pytest --cov` runs in CI.
**Status:** complete — 317 passed, 50.35% coverage ≥ threshold

## Problem

CI ran `pytest` without `--cov-fail-under`, so test coverage could regress
silently. The BACKLOG asked: read the current CI baseline, then set the
`--cov-fail-under` floor equal to that number.

## Actions taken

### `requirements-dev.txt`
- Added `pytest-cov>=5.0.0` (was missing; CI was not actually running coverage).

### `.github/workflows/test.yml`
- Updated `pytest` invocation to:
  ```
  pytest -v --tb=short --color=yes \
    --cov=bot --cov=watchdog \
    --cov-report=term-missing \
    --cov-fail-under=50
  ```
- Measured baseline before committing: **50.35%** (317 tests, including the 12
  new stale-state regression tests from feature 031).
- Threshold set at **50%** — ratchet upward as new tests land.

## Notes
- `--cov=bot --cov=watchdog` matches the two source packages; `scripts/` and
  one-off entry points are excluded (they are not tested at package level).
- Future runs should raise the threshold by 1–2 % each time new tests land to
  maintain upward pressure without a big one-time jump.
