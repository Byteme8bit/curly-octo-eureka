# Feature 031 — CI coverage threshold (`--cov-fail-under=45`)

**Status:** complete

## Problem

`pytest --cov` was not yet wired into CI, so coverage regressions were silent.

## Changes

### `requirements-dev.txt`
- Added `pytest-cov>=5.0.0`.

### `.github/workflows/test.yml`
- pytest step now runs:
  ```
  pytest -v --tb=short --color=yes \
    --cov=bot --cov=watchdog \
    --cov-report=term-missing \
    --cov-fail-under=45
  ```
- Baseline measured at **47.14%** (288 tests, 7 255 statements).
- `--cov-fail-under=45` gives a small safety margin while still failing on
  meaningful regressions; ratchet upward as coverage grows.

## Verification

```
pytest --cov=bot --cov=watchdog --cov-report=term-missing --cov-fail-under=45
# Required test coverage of 45% reached. Total coverage: 47.14%
# 288 passed
```
