# 018 — Dedicated paper portfolio snapshot file

**Requested:** 2026-05-25
**Status:** awaiting verification — pytest pending

## Request
> are we logging the paper portfolio in a separate file somewhere? I think that would be best if not. The bot can update this file with the holdings and then load/print this as needed.

## Prior state
- **`.paper_state.json`** — full broker state (balances, cost basis, trades, risk). Machine-oriented, not ideal for quick inspection.
- **Rotating session logs** — portfolio lines embedded in tick logs, not a single dedicated snapshot file.

## Actions taken
- **`bot/paper_portfolio.py`** — `PaperPortfolioLog` writes/reads `paper_portfolio.json` with:
  - `updated_at`, `portfolio_usd`, `baseline_pnl`, `drawdown_pct`
  - per-asset `qty`, `usd_price`, `usd_value`
- **`config.py`** — `paper_portfolio_file` setting (`PAPER_PORTFOLIO_FILE`, default `paper_portfolio.json`).
- **`bot/engine.py`**
  - Updates portfolio file every tick after market refresh.
  - Rewrites on `TradeBot -reset`.
  - Startup banner loads holdings + last saved summary from portfolio file when present.
- **`bot/display.py`** — shows portfolio summary line + file path on startup.
- **`scripts/show_portfolio.py`** — CLI to print snapshot anytime.
- **`.env.example`**, **`.gitignore`** — document path; gitignore local snapshot.
- **`tests/test_paper_portfolio.py`** — write/load/format/clear tests.

## Usage
```powershell
# View current snapshot (while bot is stopped or running)
.\.venv\Scripts\python.exe scripts\show_portfolio.py

# File location (default)
# C:\Users\lynch\eth-trading-bot\paper_portfolio.json
```

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_paper_portfolio.py -v
```

Restart bot — after startup (before first tick) `paper_portfolio.json` should exist. `show_portfolio.py` bootstraps from `.paper_state.json` if the snapshot file is missing.
