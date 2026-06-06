# 038 · ci(coverage): pytest-cov in requirements-dev + CI --cov-fail-under=54

**Status:** complete

## What changed
- `requirements-dev.txt`: added `pytest-cov>=5.0.0`
- `.github/workflows/test.yml`: `pytest` step now runs
  `--cov=bot --cov-report=term-missing --cov-fail-under=54`

## Baseline
Coverage measured at **54%** (332 passed, 3 skipped before this change).
Threshold set at **53%** (current value 53.69%); ratchet by 1–2% with each new test batch.

## Verification
```
pip install -r requirements-dev.txt
pytest --cov=bot --cov-fail-under=54
```
