# 077 — Paper mirror-live alignment (stop phantom wins)

**Requested:** 2026-06-17
**Status:** complete — awaiting verification

## Request
Align paper to live mirror gates so paper only executes trades live would take;
re-anchor paper to live balances; probe routes; execute live only if net > 0.05%.

## Actions taken
- `config.py` — `PAPER_MIRROR_LIVE_ONLY` (default `1` when `LIVE_MIRROR_PAPER=1`)
- `bot/engine.py` — `_paper_mirror_live_would_block` before paper execution in tick,
  `_try_execute_intent`, and force-trade evaluation; blocks non-live routes, profit-only
  failures, defensive ETH→USD trims, and live constraint violations
- `scripts/probe_eth_ada_routes.py` — probe all single-hop among ETH/ADA/BTC/USD
- `.env` (not committed) — `PAPER_MIRROR_LIVE_ONLY=1`
- `tests/test_profit_only_mode.py` — mirror-live gate coverage

## Verification
```powershell
.\.venv\Scripts\python.exe scripts\probe_eth_ada_routes.py
.\.venv\Scripts\python.exe scripts\anchor_paper_to_live.py
.\.venv\Scripts\python.exe -m pytest tests/test_profit_only_mode.py tests/test_live_mirror.py -q
```

## Notes
No positive routes at probe time (~-0.45% best net); no live fill attempted.
