# 034 — Pre-flight reject messages in basis points

**Requested:** BACKLOG "Soon" — show basis points instead of raw decimals in
pre-flight reject messages.
**Status:** complete — 317 passed

## Problem

Pre-flight log lines looked like:
```
Pre-flight reject: net -0.0035 (gross +0.0040 - fees 0.0040 - slippage 0.0005) <= min 0.0020
```

Raw four-decimal fractions are harder to read at a glance than basis points,
especially when diagnosing fee/slippage budget issues.

## Actions taken

### `bot/preflight.py`

- Added `_bps(pct: float) -> str` helper: `round(pct * 10_000)` → `"Nbps"`.
- Updated both the reject and the OK reason strings:
  - Before: `net -0.0035 (gross +0.0040 - fees 0.0040 - slippage 0.0005) <= min 0.0020`
  - After:  `net -35bps (gross 40bps - fees 40bps - slippage 5bps) <= min 20bps`

Existing tests (`test_fee_gate.py`) assert only on `res.allowed` and
`res.net_return_pct`, not on the reason string — no test changes required.

## Notes

The `gross_return_pct`, `fee_pct`, `slippage_pct`, and `net_return_pct` fields
on `PreFlightResult` are unchanged (raw fractions) for downstream code that
reads them numerically. Only the human-readable `reason` string changes.
