# 038 — CI coverage threshold (pytest-cov, --cov-fail-under=50)

**Requested:** 2026-06-05 (automation cycle)
**Status:** complete

## Request

Pin a minimum coverage threshold so CI fails on regressions.
Start at the current measured baseline (≈54 %) and enforce it at 50 %.

## Actions taken

### `requirements-dev.txt`

Added `pytest-cov>=5.0.0`.

### `.github/workflows/test.yml`

Updated the `Run pytest` step's `run:` line:
```
pytest -v --tb=short --color=yes --cov=bot --cov-report=term-missing --cov-fail-under=50
```

## Verification

Current total coverage: **53.93 %** (measured locally after change).
```
python3 -m pytest tests/ --cov=bot --cov-fail-under=50 -q
```
Exit code 0 — threshold met.
