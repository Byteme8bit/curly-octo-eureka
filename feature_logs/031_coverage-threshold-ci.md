# 031 — Pin minimum coverage threshold in CI

**Requested:** 2026-05-31 (BACKLOG "Now" item)
**Status:** complete

## Request
CI emits coverage but doesn't fail on regressions. Add `--cov-fail-under`
starting at the current measured number so future regressions are caught.

## Actions taken

### `requirements-dev.txt`
- Added `pytest-cov>=5.0.0`.

### `.github/workflows/test.yml`
- CI run step now passes:
  ```
  --cov=bot --cov=watchdog
  --cov-report=term-missing:skip-covered
  --cov-fail-under=47
  ```
- Measured baseline: **47.14%** total coverage (bot + watchdog packages).
- CI will fail if coverage drops below 47 %.

### `.gitignore`
- Added `.coverage` and `htmlcov/` to avoid committing artefacts.

## Verification
288 passed; `Required test coverage of 47% reached. Total coverage: 47.14%`.
