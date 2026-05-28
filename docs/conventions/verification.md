# Verification protocol

A feature is **not done** until it has been verified. Verification means at least one of the following actually ran and passed.

## What counts as verification

| Tier | Means |
|------|-------|
| **A — Automated test** | A `pytest` test in `tests/` exercises the new behaviour and passes. Strongly preferred. |
| **B — Smoke script** | A short `scripts/verify_<feature>.py` that exercises the code path and prints `OK` / `FAIL`. Acceptable when mocking is awkward. |
| **C — Live observation** | Operator runs `python main.py` and confirms expected behaviour in logs / Discord. Acceptable for runtime integration (e.g. heartbeat timing) but must be noted in the feature log. |

Static review alone (reading the diff) is **not** verification.

## Workflow per feature request

1. Receive request → create `feature_logs/NNN_<short-name>.md` with status `in progress`.
2. Implement changes.
3. Write or update tests / smoke script.
4. **Run them.** If shell is unavailable, leave a one-line command in the feature log and mark status `awaiting verification`.
5. Update feature log **Verification** section with the actual test names / command used.
6. Status → `complete` only after step 4 actually passed.

## Running the suite

```powershell
cd C:\Users\lynch\eth-trading-bot
.\.venv\Scripts\python.exe -m pytest          # all
.\.venv\Scripts\python.exe -m pytest tests/test_portfolio_constraints.py -v
```

## When verification cannot run in-agent

The Cursor agent shell on Windows is currently sandbox-locked (see `feature_logs/007`). In that state:

- Write the test code anyway.
- Mark the feature log status `awaiting verification — sandbox locked` and surface the command the user should run.
- When sandbox is fixed, run pytest and update statuses in one pass.

## Conventions for tests

See `docs/conventions/patterns.md#10-test-patterns`.

## Continuous coverage targets

Eventually (not enforced yet):

- Every domain module has at least one happy-path and one failure-path test.
- Every persisted state class has a `tmp_path`-based round-trip test.
- Every external IO module has a mocked-retry test.
