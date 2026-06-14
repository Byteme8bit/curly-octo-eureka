# 050 — Fix no trades: edge gate + adaptive exhaustion

**Requested:** 2026-06-13
**Status:** awaiting verification — pytest pending
**Branch:** `feature/050-fix-no-trades-edge-adaptive`
**Request-ID:** 050

## Request

TradeBot still not trading after PR #49 adaptive resume fix. Diagnose
thoroughly and fix whatever is actually blocking; deliver working trades or
clear explanation with config fix applied.

## Root cause

PR #49 resume logic was correct but insufficient — three compounding blockers:

1. **Auditor `MIN_TRADE_EDGE=0.0115`** (runtime_overrides.json) vs flat-market
   cross_momentum edges ~0.0055–0.0065 → strategy never emits intents
   (`net_edge <= 0`).
2. **`adaptive_suspended: true`** with only ~40 min since suspend — 2h cooldown
   not elapsed; strict thresholds shown as "need +0.0115".
3. **`record_adaptive_attempt()` ran before execution** when intents existed —
   three ticks with downstream gate failures re-suspended adaptive in ~45s
   without a qualifying execution attempt.

Bot was alive (PID 76336, tradebot.lock), Discord listener up, no crash hold,
no risk pause. Last trade 2026-06-10 (~55h idle).

## Actions taken

- `runtime_overrides.json` — `MIN_TRADE_EDGE` **0.0115 → 0.006** (gitignored user file).
- `bot/risk.py` — resume adaptive immediately when idle ≥ 24h (skip suspend cooldown).
- `bot/engine.py` — count adaptive exhaustion only after preflight qualifies an intent.
- Tests: `test_adaptive_resume.py` (prolonged idle), `test_adaptive_attempt_counting.py`.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_adaptive_resume.py tests/test_adaptive_attempt_counting.py -q
.\scripts\start_tradebot.ps1   # after stopping old PID
```

Expect ticks to show intents with edge ~0.0065 clearing required ~0.006, or
adaptive mode at 50% relax within one tick (55h idle bypasses suspend cooldown).

## Notes

Restart required to load code + runtime_overrides. Auditor may re-propose
MIN_TRADE_EDGE later; flat-market floor is ~0.0055 for 2-hop held swaps.
