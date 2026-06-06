# 040 · feat(ux): pre-flight reject messages in basis points

**Status:** complete

## What changed
- `bot/preflight.py`:
  - Added `_bps(pct)` helper that formats a decimal fraction as `+NNbps`
  - Reject reason now reads `Pre-flight reject: net -35bps (gross +40bps - fees 40bps - slippage 5bps) <= min 5bps`
  - OK reason now reads `Pre-flight OK: net +55bps`
- `tests/test_fee_gate.py`:
  - `test_reject_reason_shows_bps` — asserts `"bps"` in reason and raw
    decimals absent
  - `test_ok_reason_shows_bps` — same for the allowed path

## Why
Raw decimals (`+0.0040`) are harder to scan than `+40bps`.  The change
is cosmetic only; decision logic is unchanged.

## Verification
```
pytest tests/test_fee_gate.py -v
```
