# 042 — Goal evolution & crash hold

**Requested:** 2026-06-10
**Status:** awaiting verification — pytest pending

## Request
TradeBot should evolve and have goals. IF it hits certain thresholds like now the portfolio is at 10k, 100k, 1m It starts to expand and venture into new strats. But also should have hard stop points in case of market crashes it knows to hold.

## Actions taken
- `bot/goal_evolution.py` — milestone tiers, strategy unlocks, crash-hold guard, persisted state (`.tradebot_goals_state.json`)
- `bot/engine.py` — per-tick goal/crash evaluation, strategy filtering via `StrategyContext.allowed_strategies`, governor exploration override, whale-follow sizing bump at tier 3
- `bot/orchestrator.py` / `bot/strategies/base.py` — skip strategies not unlocked for current tier
- `config.py` / `.env.example` — `GOAL_*` and `CRASH_HOLD_*` settings (default ON)
- `dashboard/parsers/goals.py`, `dashboard/service.py`, `dashboard/static/*` — Goals panel + overview snapshot card
- `tests/test_goal_evolution.py` — tier transitions, no duplicate spam, crash hold block/recovery

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_goal_evolution.py tests/test_dashboard.py tests/test_strategy_governor.py -q
```

Enable (default on; paper only):
```
GOAL_EVOLUTION_ENABLED=1
CRASH_HOLD_ENABLED=1
```
Restart TradeBot after editing `.env` to pick up tier gating.

## Notes
- At ~$3.4k portfolio the bot stays on tier 0 (cross_momentum only) until $10k.
- Crash hold blocks new offensive risk at 8% drawdown; recovery at 5% after 30 min minimum.
- Complements watchdog pause/hibernate — defers when risk already paused.
