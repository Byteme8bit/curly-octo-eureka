# 039 — Overview layout fix (no blank void)

**Requested:** 2026-06-09
**Status:** complete

## Request

Overview tab showed a large empty dark grid area (~60% viewport) between the header and metrics/charts. User wanted it useful or collapsed.

## Root cause

CSS Grid auto-placement conflict: `body { grid-template-rows: auto auto 1fr }` plus sidebar `grid-row: 2 / 4` reserved row 3's `1fr` track in column 1 with no content. Metrics strip and main content were pushed to implicit rows 4–5, leaving a ~560px void showing the body grid background. Fixed by switching to a flex column + sidebar layout.

## Actions taken

- **`dashboard/static/styles.css`** — replace body CSS grid with flex layout (`layout-body` / `primary-column`) to eliminate sidebar row conflict; compact chart heights
- **`dashboard/static/index.html`** — overview snapshot panel inside `#overview` below metric strip
- **`dashboard/static/app.js`** — `renderOverviewSnapshot()` cards: holdings, last trade, bot status, latest activity, blocked/hurdle note (all from `/api/overview`)

## Verification

- `pytest tests/test_dashboard.py` green
- Dashboard restart; Overview shows metrics → snapshot cards → charts with no empty void
