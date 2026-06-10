# 041 — Whale follow trading

**Requested:** 2026-06-09
**Status:** awaiting verification - pytest pending

## Request
TradeBot should try and act like a whale trades if and when possible — follow whale direction / trade with whale-like conviction when conditions allow.

## Actions taken
- `bot/strategies/whale_follow.py` — direction inference, cooldown, edge estimate, intent builder, Discord copy
- `bot/engine.py` — `_maybe_whale_follow` after whale poll; shared `_try_execute_intent` gate pipeline
- `bot/whale_watch.py` — `annotate_event` persists `follow_status` / `follow_reason` on state events
- `config.py` / `.env.example` — `WHALE_FOLLOW_*` settings (default OFF)
- `dashboard/static/app.js` — Follow column with followed/skipped badges
- `tests/test_whale_follow.py` — direction, cooldown, preflight gate, constraints

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_whale_follow.py tests/test_whale_watch.py tests/test_dashboard.py -q
```

Enable (paper only, no live order changes):
```
WHALE_WATCH_ENABLED=1
WHALE_FOLLOW_ENABLED=1
```
Restart TradeBot after editing `.env`.

## Notes
- Whale follow runs outside the strategy orchestrator but uses the same portfolio, preflight, and risk gates.
- Cooldown is per-asset (`WHALE_FOLLOW_COOLDOWN_SEC`) with hourly cap (`WHALE_FOLLOW_MAX_PER_HOUR`).
- Skipped follows post a short Discord note when Discord is enabled.
