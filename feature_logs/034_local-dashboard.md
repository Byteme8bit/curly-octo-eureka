# 034 — Local self-hosted dashboard

**Requested:** 2026-06-02
**Status:** awaiting verification — pytest pending

## Request

Create a local self-hosted dashboard that visualizes TradeBot actions, Watchdog
actions/reports, and Auditor analysis — read-only, no interference with the
running bot.

## Actions taken

- **`dashboard/`** — FastAPI + vanilla JS/CSS UI
  - `config.py` — paths from env (`DASHBOARD_*`, existing bot paths)
  - `io_util.py` — Windows-safe read with retry
  - `parsers/tradebot.py` — portfolio, receipts, window-log ticks, blocked ops
  - `parsers/watchdog.py` — `.watchdog_state.json`, `compute_health`, log filter
  - `parsers/auditor.py` — proposals, overrides, `reports/`, discord chat tail
  - `app.py` — `/api/overview`, per-tab APIs, static files
  - `__main__.py` — `python -m dashboard`
- **`tests/test_dashboard.py`** — parser fixtures + FastAPI smoke test
- **`requirements.txt`** — `fastapi`, `uvicorn[standard]`
- **`requirements-dev.txt`** — `httpx` for TestClient
- **`.env.example`** — `DASHBOARD_HOST`, `DASHBOARD_PORT`, `DASHBOARD_REFRESH_SECONDS`

## How to run

```powershell
cd C:\Users\lynch\eth-trading-bot
.\.venv\Scripts\pip.exe install -r requirements.txt
.\.venv\Scripts\python.exe -m dashboard
```

Open **http://127.0.0.1:8765/** (or port from `.env`). Auto-refresh every 15s
(configurable). Does not write bot state files.

## Verification

```powershell
.\.venv\Scripts\pip.exe install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests\test_dashboard.py -v
.\.venv\Scripts\python.exe -m pytest -q
```

Optional: run dashboard while `main.py` is running — confirm portfolio/receipts
update without restart.

## Notes

- Log parsing is best-effort (MARKET CHECK blocks, receipt text format).
- Health score uses the same `watchdog.scoring.compute_health` as the bot;
  re-evaluation/hibernate flags are not inferred from logs (may under-penalize).
- State files (`.watchdog_state.json`, etc.) are gitignored — dashboard reads
  them from the working tree when present.
