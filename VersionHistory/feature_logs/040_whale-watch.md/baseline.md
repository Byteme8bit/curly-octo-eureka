# 040 — Whale watch monitoring

**Requested:** 2026-06-09
**Status:** complete

## Request
Add whale-move monitoring that TradeBot watches during its run loop AND the dashboard displays. Whale moves = large on-chain transfers, exchange inflows/outflows, or large market trades depending on what's feasible with existing infra.

## Actions taken
- **v1 approach:** Kraken public market data (Option B) — large trades via `fetch_trades` and volume spikes from candle RVOL-style comparison. No new API keys; alert-only (no auto-trading).
- `bot/whale_watch.py` — detection, dedup, state persistence to `.whale_watch_state.json`
- `bot/data.py` — `fetch_trades()` with retry/fallback
- `config.py` / `.env.example` — `WHALE_WATCH_*` settings
- `bot/engine.py` — polls during main run loop; Discord posts via TradeBot source
- Dashboard — `build_whale_view`, `/api/whales`, overview snapshot card, Whales nav panel
- `tests/test_whale_watch.py` — detection, threshold, persistence, poll interval

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_whale_watch.py tests/test_dashboard.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

Enable: set `WHALE_WATCH_ENABLED=1` in `.env` and restart TradeBot. Dashboard picks up `.whale_watch_state.json` automatically (refresh dashboard static if already running).

## Notes
- On-chain / Whale Alert APIs deferred — no keys in `.env.example`.
- Volume spike uses configured candle timeframe (default 5m) vs prior 12 candles.
