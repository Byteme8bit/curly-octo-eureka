# 037 - Atomic route rollback

**Requested:** 2026-06-04 11:11 UTC
**Status:** complete

## Request
Deep bug-finding automation focused on recent commits and high-severity correctness bugs. Fix only concrete critical issues with a minimal, high-confidence change.

## Actions taken
- Fixed `PaperBroker.execute_path` so failed multi-leg route execution restores pre-route balances and cost basis before returning `None`.
- Added a regression test proving a failed later leg cannot leave first-leg balance mutations to be saved later.

## Verification
- `python -m pytest tests/test_triangular_arbitrage.py`

## Notes
- The bug could persist corrupted `.paper_state.json` balances if a route failed after mutating an earlier leg and a later operation saved broker state.
