# 045 — Independent trade verifier

**Requested:** 2026-06-10
**Status:** awaiting verification - pytest pending

## Request
Build a standalone Independent Verifier that reads primary sources (`.paper_state.json`, receipts, logs) and assesses real-world viability per trade with CONFIRM / DENY / UNCERTAIN verdicts. CLI, tests, docs, optional JSON/HTML reports.

## Actions taken
- Added `bot/verifier/` package: config, parsers, kraken (public ccxt), checks, core, report, `__main__`
- Added `scripts/verify_trades.py` CLI wrapper
- Added `tests/test_verifier.py` with mocked ccxt fixtures
- Added `docs/independent-verification.md`
- Extended `.env.example` with `VERIFIER_*` knobs

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_verifier.py -q
.\.venv\Scripts\python.exe scripts\verify_trades.py --last 5
.\.venv\Scripts\python.exe scripts\verify_trades.py --json
```

## Notes
- Log correlation uses window logs (`logs/*_PDT.log`) and `bot.log` if present.
- Full-history runs hit Kraken public API; OHLCV is cached per symbol/time bucket.
- Triangular / multi-hop trades intentionally skew UNCERTAIN for live atomicity risk.
