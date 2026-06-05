# 037 - Paper broker path rollback

**Requested:** 2026-06-05 04:05 PDT
**Status:** complete

## Request
We are fixing a likely high-severity bug in /workspace: bot/paper_broker.py PaperBroker.execute_path mutates balances leg-by-leg, but if leg 2+ fails, it returns None without rolling back earlier balance mutations. Concrete trigger: first leg passes min_usd_trade, fee reduces proceeds below min_usd_trade so second leg fails; engine treats it as no trade, but in-memory balances are corrupted and may later be persisted. Please verify the root cause with runtime-oriented analysis, propose minimal fix and regression test. You may inspect/modify code if needed, but keep changes focused. Return exact findings and suggested test command(s).

## Actions taken
- Verified the failure with a runtime reproduction using a two-leg USD->ETH->ADA route.
- Added an atomic rollback in `PaperBroker.execute_path` by snapshotting balances and cost basis before route execution and restoring them if any leg fails.
- Added a regression test that recreates the fee-below-min second-leg failure and asserts no balances, cost basis, trades, or state file are mutated.

## Verification
- `python3 - <<'PY' ... PY` runtime reproduction: returned `None` with balances restored to `{'USD': 5.0}`, empty cost basis, no trades, and no state file.
- `python3 -m pytest tests/test_triangular_arbitrage.py -q`
- `python3 -m pytest -q`

## Notes
- Runtime debug logs confirmed the original corruption: leg 1 changed balances from `{'USD': 5.0}` to `{'USD': 0.0, 'ETH': 0.002475}` and set ETH cost basis to `4.95`, then leg 2 returned `None`.
