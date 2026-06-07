# Feature 039 — ci(coverage): pytest-cov + fail-under threshold

## Status
completed

## Problem
CI ran `pytest` but never measured or enforced coverage, so regressions in
test coverage went undetected.

## Fix
- Added `pytest-cov>=5.0.0` to `requirements-dev.txt`.
- Added `--cov=bot --cov-report=term-missing --cov-fail-under=54` to the
  `pytest` step in `.github/workflows/test.yml`.

The threshold (54%) matches the measured baseline on this branch.  Ratchet
it upward by 1–2 percentage points each time new tests land.

## Files changed
- `requirements-dev.txt` — added `pytest-cov>=5.0.0`
- `.github/workflows/test.yml` — added cov flags to pytest invocation

## Verification
```
pip install pytest-cov
pytest --cov=bot --cov-report=term-missing --cov-fail-under=54
```
