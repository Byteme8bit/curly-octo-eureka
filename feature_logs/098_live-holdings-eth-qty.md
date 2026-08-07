# 098 — Live holdings from paper state + visible ETH qty

**Requested:** 2026-08-07 03:55 PDT
**Status:** complete

## Request
User still does not see holdings updating on the dashboard.

## Root cause
API holdings were updating (ETH qty drifting via triangular loops), but:
1. Overview chips were easy to miss / cache-stale JS
2. Holdings composition stays ETH/USD/SOL (closed-loop arb) so it *looks* frozen
3. Qty came from `paper_portfolio.json` only — now overlaid from `.paper_state.json`

## Actions taken
- Holdings qty always from `.paper_state.json`
- Metric strip **ETH qty**; chips highlight qty; timestamp under Holdings
- `Cache-Control: no-store` on HTML/static; `app.js?v=051`
- Deploy + restart dashboard

## Verification
Hard-refresh https://lynch.gdn/tradebot/ — top strip **ETH qty** should tick (e.g. 0.572 → 0.573…) as triangles fill.
