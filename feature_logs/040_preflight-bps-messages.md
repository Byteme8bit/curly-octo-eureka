# 040 — Pre-flight reject messages in basis points

**Requested:** 2026-06-05 (automation cycle)
**Status:** complete

## Request

Pre-flight reject messages showed raw decimals like
`gross +0.0012 - fees 0.0040 - slippage 0.0005`, which is hard to read at a
glance.  Show basis points (bps) instead.

## Actions taken

### `bot/preflight.py`

Added a local `_bps(v)` helper inside `validate()` that converts a fraction
to a signed integer bps string (e.g. `0.004 → "+40bps"`).

Updated both message formats:
- Reject: `"Pre-flight reject: net +Xbps (gross +Ybps - fees Zbps - slippage Wbps) <= min Mbps"`
- OK: `"Pre-flight OK: net +Xbps"`

Raw decimal fractions (`0.XXXX`) no longer appear in either reason string.

### `tests/test_fee_gate.py`

- `test_reject_reason_uses_bps` — asserts `"bps"` in reason, asserts no `0.XXXX` pattern.
- `test_allow_reason_uses_bps` — same check for the OK path.

## Verification

```
python3 -m pytest tests/test_fee_gate.py -v
```
Expected: 6 tests pass (4 original + 2 new).
