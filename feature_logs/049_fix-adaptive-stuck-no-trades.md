# 049 — Fix adaptive stuck + clarify zero-trade summaries

**Requested:** 2026-06-12
**Status:** awaiting verification — pytest pending
**Branch:** `feature/049-fix-adaptive-stuck-no-trades`
**Request-ID:** 049

## Request

TradeBot reports "0 trades" hourly since PR #48. Diagnose whether live_tag or
quiet mode broke execution; restore trading.

## Root cause

PR #48 did **not** break the trade path — `live_tag` is Discord-only and already
wrapped in try/except. The bot was idle because:

1. Auditor `runtime_overrides.json` sets `MIN_TRADE_EDGE=0.0115` (flat market
   edges ~0.003–0.010).
2. Adaptive relaxation had **exhausted** (`adaptive_suspended: true` in
   `.paper_state.json`) and never re-activated, leaving strict thresholds forever.
3. PR #48's new hourly summaries made the stall visible as "Trades: 0" each hour.

## Actions taken

- `bot/risk.py` — track `adaptive_suspended_at`; auto-resume adaptive after
  `IDLE_REEVAL_HOURS` cooldown (legacy states without timestamp resume after
  `2 × IDLE_REEVAL_HOURS` total idle).
- `bot/paper_broker.py` — `RiskState.adaptive_suspended_at` field.
- `bot/engine.py` — hourly activity buffer counts execution gate blocks only,
  not strategy "below fee hurdle" notes (avoids misleading 400+ blocked/hour).
- Tests: `test_adaptive_resume.py`, `test_live_verify_trade_path.py`.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_adaptive_resume.py tests/test_live_verify_trade_path.py tests/test_live_verify_tag.py tests/test_quiet_discord.py -q
```

Restart TradeBot after deploy so adaptive resume logic loads.
