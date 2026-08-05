# 085 — Enable stat_arb and triangular_arbitrage

**Requested:** 2026-08-04
**Status:** awaiting verification - user restart pending

## Request
Enable arbitrage strategies for more paper trading activity after 084 fee-align tuning.

## Actions taken
Updated `.env` (local, not committed):
- `STRATEGIES=cross_momentum,stat_arb,triangular_arbitrage`
- `STAT_ARB_ZSCORE_THRESHOLD=2.2` (from 2.5 — slightly more mean-reversion signals)

Goal tier 0 already allows both arbs in `GOAL_TIER0_STRATEGIES`. Bot restart required.

## Verification
```powershell
.\scripts\start_tradebot.ps1
Select-String -Path logs\bot_stdout*.log -Pattern "Loaded strategies" | Select-Object -Last 1
Get-Content logs\trade_diagnosis.json -Raw | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('blocked',[])[:3])"
```
Expect startup log: `Loaded strategies: cross_momentum, stat_arb, triangular_arbitrage`.

## Notes
Triangular loops use closed-loop ETH exemption (feature 036). `MIN_ETH_RESERVE=0.45` with ~0.48 ETH — thin margin for open ETH sells; arbs may still emit USD-start paths.
