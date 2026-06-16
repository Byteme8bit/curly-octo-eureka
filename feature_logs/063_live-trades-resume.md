# 063 — Resume live Kraken fills

**Requested:** 2026-06-15 (urgent)
**Status:** awaiting verification — pytest + live fill poll pending

## Request
Get real Kraken live fills again. Keep LIVE_DRAWDOWN_HALT_PCT=0.10, route caps, and PROFIT_ONLY / strict profit for offensive trades. Allow 4-leg triangular live mirror; tune .env; commit auditor fixes; restart and verify.

## Root cause
1. **Primary:** Paper triangular arb uses 4-leg loops; `LIVE_MAX_ROUTE_LEGS=3` blocked every live mirror (`Route has 4 legs`).
2. **Secondary:** Paper hourly cap hit (26/25) — no new paper trades → no mirror attempts until window reset or limit raised.
3. **Correct skips:** Single-hop UNI/cross trades tagged DENY (negative net after fees) — kept blocked per user.
4. **DCA idle:** Paper USD = $0; live has ~$266 USD — DCA could not schedule without live balance hint.

## Actions taken
- `.env` (not committed): `LIVE_MAX_ROUTE_LEGS=4`, `MAX_TRADES_PER_HOUR=40` (unblock paper flow).
- `bot/strategies/base.py`: `StrategyContext.live_usd_balance` for mirror-mode DCA scheduling.
- `bot/engine.py`: populate `live_usd_balance` from Kraken holdings in mirror mode.
- `bot/strategies/equity_dca.py`: use `max(paper_usd, live_usd)` when context provides live balance.
- `tests/test_live_guards.py`: 4-leg triangular route allowed when `max_route_legs=4`.
- Included prior uncommitted fixes: `bot/auditor_service.py`, `watchdog/engine.py`, `tests/test_watchdog_live_gains.py`.

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_live_guards.py tests/test_live_mirror.py tests/test_equity_dca.py tests/test_auditor.py tests/test_watchdog_live_gains.py -q
.\scripts\start_tradebot.ps1
# Poll up to 10 min: tail logs/live_mirror_skips.log; check .live_state.json for new live entry
.\.venv\Scripts\python.exe scripts\is_tradebot_running.py
```

## Notes
- `live_broker.execute_path` already runs sequential legs with rollback — no broker code change needed for 4 hops.
- `MIN_NET_PROFIT_PCT=0.0005` left unchanged; triangular routes show +3% net on paper.
