# 055 — WatchDog live gain alerts (paper/live split)

**Requested:** 2026-06-15
**Status:** awaiting verification — pytest pending

## Request

WatchDog pinned "Major portfolio gain" messages showing ~$5,688 (+243%) while
real Kraken spot is ~$1,644. With `LIVE_MIRROR_PAPER=1` + `LIVE_ENABLED=1`,
gain/milestone pins must use live Kraken portfolio and session PnL, not paper
simulation. Fix milestone spam; label paper separately; audit TradeBot Discord.

## Actions taken

- `bot/live_portfolio.py` — shared live spot snapshot loader
- `watchdog/config.py` — `LIVE_ENABLED`, live state paths, milestone cooldown
- `watchdog/state.py` — separate live/paper band tracking + cooldown timestamp
- `watchdog/engine.py` — live portfolio check; skip paper log milestones when live
- `bot/report.py` — milestone alert labels (Live Kraken vs `[Paper sim]`)
- `bot/engine.py` — TradeBot milestone pins + hourly summary use live metrics
- `bot/discord_summary.py` — dual live/paper lines in hourly summary
- `tests/test_watchdog_live_gains.py` — live vs paper alert behavior

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_watchdog_live_gains.py -v
.\.venv\Scripts\python.exe -m pytest tests\test_watchdog_state.py -v
```

Restart bot after merge. With live armed, paper portfolio spikes should not pin;
WatchDog heartbeat should show "Live Kraken spot $…".

## Notes

- Kraken Trade Prop ($5k) is a separate account — never included in live spot.
- Default `WATCHDOG_MILESTONE_COOLDOWN_MINUTES=60` limits rapid milestone pins.
