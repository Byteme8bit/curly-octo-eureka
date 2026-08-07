# 097 — Holdings qty display + honest session PnL

**Requested:** 2026-08-07 03:46 PDT
**Status:** complete

## Request
PERMISSION GRANTED: fix holdings display + session PnL

## Actions taken
- `dashboard/static/app.js` — holdings chips/table show **qty · $**; trades caption uses **book PnL** (`baseline_pnl`) plus corrected trade edges
- `dashboard/parsers/series.py` — build paper series from `.paper_state.json`; correct legacy closed-loop notional `gain_loss`
- `dashboard/static/index.html` — cache bump `app.js?v=050`
- Deployed + restarted `tradebot-dashboard.service`

## Verification
Hard-refresh https://lynch.gdn/tradebot/ — holdings show qty; chart caption book PnL ~tens of $, not ~$10k.
