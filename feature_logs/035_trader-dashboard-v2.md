# 035 — Trader dashboard v2 (command center)

**Requested:** 2026-06-02
**Status:** awaiting verification — pytest pending

## Request

Transform the local dashboard into a single-page trader cockpit with portfolio
strip, Chart.js graphs, WatchDog/Auditor panels, forecasts from audit reports,
and a unified activity timeline.

## Actions taken

- **`dashboard/parsers/series.py`** — portfolio history from window logs, daily
  trade buckets from receipts, forecast table parser from audit markdown
- **`dashboard/parsers/timeline.py`** — merged trade / watchdog / auditor events
- **`dashboard/parsers/tradebot.py`** — numeric gain/loss parsing, cash %, trade count
- **`dashboard/parsers/auditor.py`** — forecast bands on report summaries
- **`dashboard/service.py`** — summary strip; overview embeds forecasts + timeline
- **`dashboard/app.py`** — v0.2.0; `/api/portfolio/history`, `/api/trades/series`,
  `/api/forecasts`, `/api/timeline`
- **`dashboard/static/`** — scrollable command-center layout, Chart.js CDN, dark trader theme
- **`tests/test_dashboard.py`** — forecast, timeline, new endpoint coverage

## Forecasts

Parsed from the latest `reports/**/audit-*.md` **## Forecast** markdown table
(same format as `bot/auditor/report.py`). No live forecaster invocation — read-only
display of existing audit output.

## How to run

```powershell
cd C:\Users\lynch\eth-trading-bot
.\.venv\Scripts\python.exe -m dashboard
```

Open **http://127.0.0.1:8765/** — restart dashboard if already running to pick up v2.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_dashboard.py -v
.\.venv\Scripts\python.exe -m pytest -q
```

## Notes

- Portfolio line chart uses MARKET CHECK ticks from window logs (not a separate
  snapshot history file — `paper_portfolio.json` is point-in-time only).
- Chart.js loaded from jsDelivr CDN; requires network on first load.
