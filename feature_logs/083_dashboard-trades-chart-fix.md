# 083 — Dashboard trades chart visibility fix

**Requested:** 2026-08-04 (continuation)
**Status:** complete (user confirmed dashboard OK)

## Request
Daily trades chart showed 0 trades despite API returning 2 trades on Aug 4–5; Latest Activity panel showed trades correctly.

## Actions taken
- `dashboard/static/app.js` — replace mixed bar/line chart with grouped bars (PnL left axis, trade count right axis); explicit `y1.max`; session caption text
- `dashboard/static/index.html` — add `#chart-trades-caption`, cache buster `v=048`
- `dashboard/static/styles.css` — `.chart-caption` styling

## Verification
Hard refresh dashboard (`Ctrl+Shift+R` at http://127.0.0.1:8765/):
- Caption reads e.g. `08-04–08-05: 4 trades, net -$0.76` (UTC day buckets may double-count same session trades)
- Orange bars at height 2 on right axis for each day
- Red/green PnL bars on left axis

No pytest required (static frontend only).

## Notes
Root cause: Chart.js 4 mixed bar+line with dual y-axes rendered the trade line at 0. June history (185 trades/day) was already filtered client-side since v=047.
