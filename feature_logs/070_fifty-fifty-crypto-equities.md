# 070 — 50/50 crypto/equity portfolio strategy

**Requested:** 2026-06-16
**Status:** complete — awaiting verification (pytest + restart)

## Request
50% crypto / 50% stocks/ETFs target; DCA into equities during accumulation; active crypto day trading; validated xStocks only.

## Actions taken
- **xStocks probe:** `logs/xstocks_probe.json` — validated `AAPLx,TSLAx,SPYx,NVDAx,MSFTx,GOOGLx` (318 pairs online).
- **config.py** — bucket targets (`TARGET_EQUITY_ALLOCATION_PCT`, `MAX_*_BUCKET_PCT`), accumulation flags, `CRYPTO_DAY_TRADE_MODE` + `CRYPTO_MIN_TRADE_EDGE`.
- **portfolio_constraints.py** — crypto/equity bucket math, crypto→USD defensive trims, block equity→crypto during accumulation.
- **equity_dca.py** — bucket cap, faster interval when `EQUITY_DCA_PRIORITY=1`.
- **engine.py** — constraint wiring, DCA intent priority, relaxed crypto edge.
- **report.py** — `-portfolio` shows allocation line.
- **tests/test_portfolio_allocation.py** — bucket math, accumulation blocks, crypto trim.
- **docs/dca-equities.md**, **docs/live-trading.md** — 50/50 section.
- **.env** — 50/50 profile knobs applied.

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_portfolio_allocation.py tests/test_portfolio_constraints.py tests/test_equity_dca.py -q
# Restart TradeBot; Discord `-portfolio` should show crypto/equity split vs 50/50 target
```

## Notes
- `MAX_EQUITY_ALLOCATION_PCT` remains per-symbol cap; bucket caps use `MAX_EQUITY_BUCKET_PCT` / `MAX_CRYPTO_BUCKET_PCT`.
- Invalid xStocks are stripped from `LIVE_ALLOWED_ASSETS` at startup via `filter_equity_watchlist`.
