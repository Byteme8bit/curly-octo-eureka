# 104 — Historical 7-day replay engine

**Requested:** 2026-08-14 15:46 PDT
**Status:** complete (VPS replay running)

## Request
Implement historical replay: last 7 days, accelerated sim, realistic maker/taker fees, full reset of all related state.

## Actions taken
- Added `bot/replay/` (`clock`, `store`, `data_provider`, `runner`)
- Hooks: `PaperBroker.set_clock` / `_stamp`, `TradingEngine.replay_mode` (skips whale), risk/governor clock injection
- Scripts: `scripts/reset_for_replay.py`, `scripts/run_historical_replay.py`
- Fees locked realistic: `FEE_FORCE_STATIC=0`, `PAPER_USE_MAKER_FEES=1`, `FEE_RATE=0.0016`
- Full reset: paper/watchdog/goals/discord log/baseline/portfolio + screenshot balances
- **Timeframe:** `15m` (672 bars = 7 days). Kraken public OHLC only retains ~720 candles — **5m cannot cover 7 days**
- VPS: live `tradebot` stopped; replay running ~90 min wall-clock

## Verification
```powershell
ssh ... "tail -50 /home/cursor/eth-trading-bot/logs/replay/run.log"
# summary when done:
# logs/replay/summary.json
```

## Notes
Bar-close marks (not L2). Current public fee schedule applied historically. Whale/news off during replay. Dashboard remains up for live paper view of replay fills.

**Kraken public OHLC limit:** ~720 candles → **15m** used for full 7 days (672 bars). 5m only covers ~2.5 days on public API.

Local `version_history.py` snapshots skipped this session (broken local venv Python path).
