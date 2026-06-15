# 057 — Kraken xStocks (equities v1)

**Requested:** 2026-06-15
**Status:** complete — awaiting verification (pytest pending)

## Request
Expand TradeBot to support Kraken tokenized stocks/ETFs (xStocks) on spot, with futures documented as Phase 2b. Default off; live requires explicit allowlist.

## Actions taken
- `bot/equities.py` — Kraken `tokenized_asset` REST helpers (pairs, ticker, OHLCV)
- `config.py` — `ENABLE_EQUITIES`, `EQUITY_WATCHLIST`, `MAX_EQUITY_ALLOCATION_PCT`; dynamic symbol maps on `Settings`
- `bot/data.py` — equity price/candle fetch in tick loop
- `bot/markets.py` — USD-only routes for equity assets
- `bot/portfolio_constraints.py` — separate equity concentration cap
- `bot/live_broker.py` — `asset_class=tokenized_asset` on equity orders; dynamic balance sync
- Strategies/orchestrator — use `Settings.symbol_assets` / `asset_usd_symbols`
- Dashboard — `equity_holdings` section when enabled
- `docs/kraken-equities-futures.md`, tests, `.env.example`

## Verification
awaiting verification — pytest pending

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_equities.py tests/test_live_guards.py tests/test_dashboard.py -q
```

## Notes
- ccxt `load_markets()` omits xStocks; bot uses Kraken REST with `asset_class=tokenized_asset`.
- Futures (xStocks perps on `krakenfutures`) deferred to Phase 2b.
