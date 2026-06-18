# 078 — Risky margin / futures enable

**Requested:** 2026-06-17
**Status:** complete — awaiting verification (pytest + restart)

## Request
User explicit consent: "do some risky shit, margin trade i dont care" — enable leveraged futures/margin with aggressive params, override conservative handoff defaults.

## Actions taken
- **Finding:** Kraken **spot margin** not implemented. Leveraged exposure via `bot/futures/` (Kraken perpetuals on `ccxt.krakenfutures`).
- **Live blocker:** Spot `KRAKEN_API_KEY` returns `authenticationError` on `krakenfutures`. Live perps need separate Futures API keys + funded futures wallet.
- **Enabled:** `ENABLE_FUTURES=1`, `RISKY_MARGIN_OK=1`, paper sim (not live futures until Futures keys added).
- **Watchlist:** `BTC/USD:USD`, `ETH/USD:USD`, `ADA/USD:USD` (shorting supported on all three).
- **Risk params:** 5× leverage, $150 max notional, 0.15% momentum threshold, 20% balance per trade margin slice, 18% drawdown halt.
- **`config.py`:** `RISKY_MARGIN_OK`, `FUTURES_MOMENTUM_THRESHOLD`, `FUTURES_MARGIN_PCT`, `FUTURES_DRAWDOWN_HALT_PCT`.
- **`bot/futures/manager.py`:** wired settings; clearer live-wallet-zero error when Futures keys missing.

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_futures.py -q
.\scripts\start_tradebot.ps1
# Check logs for "Futures RISKY paper sim" and existing open positions in .futures_paper_state.json
```

## Notes
- Futures path bypasses `PROFIT_ONLY_MODE` — separate momentum strategy.
- To go live: create Kraken Futures API keys, fund futures wallet, set `LIVE_FUTURES_ENABLED=1`.
- Spot live mirror unchanged (`LIVE_ENABLED=1`).
