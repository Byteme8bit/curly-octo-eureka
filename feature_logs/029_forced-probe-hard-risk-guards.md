# 029 — Forced probe hard-risk guard fix

**Requested:** 2026-06-01 04:00 PDT
**Status:** complete

## Request
> You are a deep bug-finding automation focused on high-severity issues.
>
> Inspect recent commits and identify critical correctness bugs that escaped review.
> Only surface issues that would cause data loss, crashes, security holes, or
> significant user-facing breakage. If a critical bug is found, implement a
> minimal, high-confidence fix and add or update tests when possible.

## Actions taken
- Found that forced idle probes skipped the same hard gates used by normal
  trades. During circuit-breaker re-evaluation, the main tick loop blocks
  non-defensive trades, but `_maybe_force_probe()` could still execute a new
  non-defensive position because `can_trade` remains true for defensive
  de-risking.
- Updated `bot/engine.py` so forced probes still bypass edge/fee profitability
  gates, but must pass `RiskManager.can_trade_now()` and
  `PortfolioConstraints.validate_intent()` before execution.
- Normalized forced probe intents to `strategy_name="probe"` before constraint
  validation so strategy-specific alt-cap exceptions cannot be applied to a
  deliberately edge-agnostic activity trade.
- Added `tests/test_forced_probe_guards.py` to cover risk-gate and alt-cap
  blocking before execution.

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_forced_probe_guards.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

Both commands passed with `python3` in the Linux automation environment.

## Notes
- The probe still provides guaranteed paper activity when the bot is active,
  idle, and under hard risk limits; it no longer opens new risk while paused or
  above concentration limits.
