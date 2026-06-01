# 032 — Pin minimum coverage threshold in CI

**Requested:** 2026-06-01 (automation cycle — BACKLOG "Now")
**Status:** complete

## Request

> Pin a minimum coverage threshold now that `pytest --cov` runs in CI. CI emits
> coverage but doesn't fail on regressions. Add `--cov-fail-under` (start at the
> current measured number, ratchet up). Read the latest CI run to find the
> baseline first.

## Baseline measured

Running `pytest --cov=bot --cov=watchdog` locally on `main` before this change
produced **50 %** total combined coverage across `bot/` and `watchdog/`.

## Actions taken

- **`.github/workflows/test.yml`** — updated `pytest` run step to:
  ```
  pytest -v --tb=short --color=yes \
    --cov=bot --cov=watchdog \
    --cov-report=term-missing \
    --cov-fail-under=50
  ```
  The job now fails if coverage drops below the baseline.

- **`requirements-dev.txt`** — added `pytest-cov>=5.0.0` so `--cov` is available
  without a separate manual install.

## Verification

```
pip install -r requirements-dev.txt
pytest --cov=bot --cov=watchdog --cov-report=term-missing --cov-fail-under=50
```

Exit code 0 confirms threshold is met.

## Notes

- Threshold is set at 50 % (current baseline), not higher, so it acts as a
  regression guard rather than a stretch target.
- The agent should ratchet this number up whenever new tests land and coverage
  increases.
