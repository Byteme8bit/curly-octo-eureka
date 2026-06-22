# 074 — Sync architecture docs with live trading subsystems

**Requested:** 2026-06-22 (scheduled documentation automation)
**Status:** complete

## Request
Keep technical documentation current as the codebase evolves — recently changed subsystems with weak docs, public interfaces, and operational runbooks.

## Actions taken
- **Modified** `docs/README.md` — index live trading, DCA, verifier, handoff operational docs.
- **Modified** `docs/architecture/modules.md` — add live_broker, live_portfolio, live_mirror, equities, verifier, dashboard, force_trade_log, whale modules; expand test map.
- **Modified** `docs/architecture/overview.md` — live execution modes, persistence files, diagram notes.
- **Modified** `docs/live-trading.md` — fix orphaned anchor-script section; add troubleshooting for false drawdown halt (#65/072) and resume commands.

## Verification
Docs verified against source:
- `bot/live_portfolio.py` — `load_live_usd_prices()` merge behavior
- `bot/engine.py` — `-resume-live` halt clearing
- `dashboard/parsers/live_portfolio.py` — shared loader import

## Notes
Documentation-only change; no runtime behavior modified.
