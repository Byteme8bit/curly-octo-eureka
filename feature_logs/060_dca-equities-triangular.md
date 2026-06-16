# 060 — Equity DCA + triangular arb parallel

**Requested:** 2026-06-15
**Status:** awaiting verification — pytest pending

## Request
Start DCA into stocks/ETFs while continuing crypto triangular arbitrage. Config-driven, paper + live mirror, guardrails preserved.

## Actions taken
- `bot/strategies/equity_dca.py` — scheduled USD → xStock buys with persisted `.dca_state.json`
- `bot/strategies/registry.py` — register `equity_dca`, auto-append when `DCA_ENABLED=1`
- `bot/strategies/base.py` — `is_accumulation` on `TradeIntent`
- `bot/preflight.py`, `bot/risk.py`, `bot/engine.py`, `bot/verifier/live_tag.py` — accumulation bypass (not profit-only offensive)
- `bot/strategies/triangular_arbitrage.py` — exclude equity assets from loop scan
- `config.py`, `.env.example`, `.env` — DCA knobs
- `docs/dca-equities.md`, `docs/kraken-equities-futures.md`
- `tests/test_equity_dca.py`

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_equity_dca.py tests/test_triangular_arbitrage.py -q
```

## Notes
- DCA bypasses `MIN_NET_PROFIT_PCT` / edge hurdles; still respects caps, drawdown halt, live allowlist.
- Triangular arb unchanged; `LIVE_ALLOW_TRIANGULAR=1` preserved.
