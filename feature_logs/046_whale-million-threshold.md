# 046 — Whale million-dollar threshold

**Requested:** 2026-06-10
**Status:** awaiting verification - pytest pending

## Request
Redefine "whale" thresholds to millions USD, not $50k–$100k. Defaults: $1M for large trades and volume spikes; whale-follow uses the same floor.

## Actions taken
- `config.py` — `WHALE_WATCH_MIN_USD` default `1000000`; new `WHALE_WATCH_SPIKE_MIN_USD` (defaults to trade min when unset)
- `.env.example` — updated defaults and comments
- `bot/whale_watch.py` — `WhaleWatcher.spike_min_usd` for volume-spike notional floor
- `bot/engine.py` — passes `spike_min_usd` from settings
- `tests/test_whale_watch.py`, `tests/test_whale_follow.py` — thresholds and notionals raised to $1M+
- Local `.env` updated (`WHALE_WATCH_MIN_USD`, `WHALE_WATCH_SPIKE_MIN_USD`); not committed

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_whale_watch.py tests/test_whale_follow.py tests/test_whale_watch_discord.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

Restart TradeBot after merge to pick up new thresholds (singleton lock).

## Notes
- Whale-follow still receives `min_usd=settings.whale_watch_min_usd` for conviction edge scaling; only events above the watch floor reach follow evaluation.
- PR #45 merged to main before this branch.
