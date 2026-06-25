# 074 — Documentation sync (live trading, modules, troubleshooting)

**Requested:** 2026-06-25 (scheduled documentation automation)
**Status:** complete

## Request
Keep technical documentation current as the codebase evolves — recently changed subsystems with weak docs.

## Actions taken
- **Modified** `docs/README.md` — operational doc index (live trading, DCA, verifier, handoff).
- **Modified** `docs/architecture/modules.md` — live broker/mirror/portfolio, equities, verifier, dashboard, whale/force modules.
- **Modified** `docs/architecture/overview.md` — live mirror mode, strategies, persistence files.
- **Modified** `docs/live-trading.md` — anchor script section fix, `-resume-live`, false-drawdown troubleshooting.

## Verification
Docs-only change; no pytest required. Spot-check against:
- `bot/live_portfolio.py` (`load_live_usd_prices`)
- `bot/engine.py` (`resume-live` handler)
- `tests/test_resume_live_halt.py`, `tests/test_dashboard_live.py`

## Notes
Covers gaps from features 067–072 (force command, 50/50 portfolio, valuation false halt).
