# 072 — Fix live portfolio valuation false drawdown halt

**Requested:** 2026-06-16 (urgent triage)
**Status:** verified — pytest 6/6 passed 2026-06-16

## Request
Dashboard showed 84% live drawdown / LIVE HALT while Kraken still held ~0.8 ETH + USD cash (~$1,685 actual).

## Root cause
`_load_usd_prices` preferred `paper_portfolio.json` and returned early. Paper had sold all ETH (into DOT/UNI); live still held ETH. ETH priced at $0 → portfolio ~$270 vs peak $1,724 → false 84% drawdown. Engine `_usd_prices()` only fetched prices for paper holdings; same bug triggered live circuit breaker (runtime.log 2026-06-15 10:30 PDT).

## Actions taken
- `bot/live_portfolio.py` — `load_live_usd_prices()` merges session anchor + paper prices
- `dashboard/parsers/live_portfolio.py` — use shared loader
- `bot/engine.py` — union paper+live assets for fetch; session/paper fallback when ticker missing
- `bot/auditor/context.py` — same price merge
- `tests/test_dashboard_live.py` — regression test for paper/live ETH divergence

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_dashboard_live.py -q
```

**Do not auto-clear live halt** — user must review and explicitly resume after confirming Kraken balance.

## Notes
Real session loss ~$39 (triangular arb + fees), not $1,453. Triangular arbs on 2026-06-16 lost ~$5.90 reported + ~$3.36 fees.
