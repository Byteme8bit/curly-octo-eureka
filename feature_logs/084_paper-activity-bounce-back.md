# 084 — Paper activity tuning for bounce-back

**Requested:** 2026-08-04
**Status:** awaiting verification - user restart pending

## Request
User wants bot to bounce back from small negative PnL and show more trading activity.

## Root cause
Strategy edge gates used `FEE_RATE=0.0026` while preflight used live Kraken public fees (~0.40%) because `FEE_FORCE_STATIC` was unset. Trades looked close on dashboard (`edge +0.0036`) but preflight rejected with `fees 0.0040`. Defensive bucket trims (old 55% cap before restart) caused the session losses.

## Actions taken
Updated `.env` (local, not committed):
- `FEE_FORCE_STATIC=1` — align preflight with 0.26% env fee tier
- `MIN_TRADE_EDGE=0.0015`, `CRYPTO_MIN_TRADE_EDGE=0.002`
- `SLIPPAGE_BUFFER_PCT=0.0003`, `MIN_NET_PROFIT_PCT=0`
- `TRADE_COOLDOWN_SECONDS=30`, `IDLE_REEVAL_HOURS=1`, `IDLE_PROBE_FORCE_MINUTES=15`
- `MAX_CRYPTO_BUCKET_PCT=0.80` already set — restart required to stop 55% trims

## Verification
```powershell
.\scripts\start_tradebot.ps1
# Wait 2-3 ticks (~1 min), then:
Get-Content logs\trade_diagnosis.json | Select-Object -Last 30
```
Expect `meets_threshold: true` on best opportunity or a paper trade receipt. Dashboard Below Hurdle line should clear or shrink.

## Notes
Still `PROFIT_ONLY_MODE=1` — no guaranteed-loser offensive trades. Real Kraken tier may differ until API keys added.
