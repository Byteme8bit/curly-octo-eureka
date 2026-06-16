# 071 — Expand xStock universe beyond 6 symbols

**Requested:** 2026-06-16
**Status:** complete — awaiting verification (pytest + restart)

## Request
After PR #63 merge, trade all available Kraken xStocks/ETFs (not just 6), with NVDAx/AMDx preference weighting; keep 50/50 allocation.

## Actions taken
- **bot/equities.py** — `list_online_usd_equities`, `resolve_equity_watchlist_request` (`EQUITY_WATCHLIST_MODE=all` / `*`), preference-first capping via `MAX_EQUITY_WATCHLIST`.
- **config.py** — `EQUITY_PREFERENCE_TICKERS`, `LIVE_EQUITY_AUTO_ALLOW`, `EQUITY_MOMENTUM_SCAN_MAX`, `MAX_EQUITY_POSITIONS`, `EQUITY_PREFERENCE_SCORE_BOOST`.
- **bot/data.py** — rotate OHLCV scans across large watchlists (prefs always scanned).
- **cross_momentum.py** — score boost for preference tickers.
- **equity_dca.py** — 2× DCA weight / rotation for preferences.
- **portfolio_constraints.py** — concurrent xStock position cap.
- **scripts/probe_xstocks.py** — full catalog + AMD/NVDA symbol reporting.
- **tests** — all-mode, auto-allow, cap, DCA weight, position cap.
- **.env** — all-mode watchlist, NVDAx/AMDx prefs, live auto-allow (not committed).

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_equities.py tests/test_equity_validation.py tests/test_equity_dca.py -q
.\.venv\Scripts\python.exe scripts\probe_xstocks.py
# Restart TradeBot; startup log should show ~158 xStocks loaded
```

## Notes
- Kraken catalog: 318 pair entries, 158 unique online USD xStocks; AMD trades as **AMDx**.
- Crypto `LIVE_ALLOWED_ASSETS` unchanged; xStocks auto-added when `LIVE_EQUITY_AUTO_ALLOW=1`.
