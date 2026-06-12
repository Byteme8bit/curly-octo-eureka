# 047 — Path to live trading roadmap

**Requested:** 2026-06-12
**Status:** complete (doc + verifier fee fix)

## Request
User saw WatchDog `-verify 20` with LIVE_READY: NO (0 CONFIRM, 13 DENY, 7 UNCERTAIN) and asked how to build confidence before going live. Produce phased roadmap; analyze verification report and verifier fairness.

## Actions taken
- Added `docs/path-to-live-trading.md` — phased checklist Phases 0–5, bot vs user responsibilities, when LIVE_READY shows YES/CONDITIONAL/NO
- Fixed `check_fee_realism`: pass `usd_prices`; sum per-leg expected fees for multi-hop trades (was comparing loop fees to ~$0 expected on ETH-denominated routes)
- Wired `usd_prices` from `Verifier.verify_trade` into fee check

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_verifier.py -q
.\.venv\Scripts\python.exe scripts\verify_trades.py --last 20 --summary-only
```

## Notes
- Report JSON `verification_20260612-013825.json` not in repo; analysis reproduced via `verify_trades(last=20)` against local `.paper_state.json`.
- 13/20 triangular routes → LIVE_READY NO by design (>50% multi-hop).
- Price checks UNCERTAIN on older trades: Kraken OHLCV history gap, not verifier harshness.
- Do not enable live trading or commit `.env`.
