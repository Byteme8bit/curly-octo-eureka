# 031 — CI minimum coverage threshold

**Requested:** 2026-06-01 04:00 UTC (automated maintenance cycle)
**Status:** complete

## Request
Pin a minimum coverage threshold now that `pytest --cov` can run in CI.
CI should fail on coverage regressions. Start at the current measured number,
ratchet up over time.

## Actions taken
- **`requirements-dev.txt`**: added `pytest-cov>=5.0.0`
- **`.github/workflows/test.yml`**: updated the `Run pytest` step to:
  ```
  pytest -v --tb=short --color=yes --cov=. --cov-report=term-missing --cov-fail-under=55
  ```
  - `--cov=.` — covers all project modules
  - `--cov-report=term-missing` — prints missing lines in CI log
  - `--cov-fail-under=55` — fails the job if total falls below 55%

## Verification
```
pip install pytest-cov
python3 -m pytest --cov=. --cov-fail-under=55 --tb=no -q
# Expected: 288 passed, coverage ≥ 55%
```
Measured baseline: **58.07%** (288 tests, 2026-06-01).

## Notes
- Floor set at 55% (3pp below baseline) to give a margin for slight run-to-run
  variance without being brittle.
- Next step: ratchet to 60% after adding unit tests for `bot/engine.py` and
  `watchdog/engine.py` (two files with <25% coverage today).
