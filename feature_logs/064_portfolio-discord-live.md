# 064 — Discord portfolio shows live Kraken

**Requested:** 2026-06-15
**Status:** awaiting verification — pytest pending

## Request
`TradeBot -portfolio` only showed paper sim balances in mirror mode; show live Kraken spot + labeled paper section when `LIVE_ENABLED=1`.

## Root cause
Portfolio command called `format_portfolio_summary` with paper broker snapshot only; ignored `live_broker` / `.live_state.json` even when live trading was armed.

## Changes
- `bot/report.py`: `format_portfolio_command` — live-first dual view in mirror mode; live-only label in pure live mode.
- `bot/engine.py`: `_live_portfolio_for_command`, `_format_portfolio_response` wired to portfolio + reset replies.
- `tests/test_portfolio_command.py`: formatting tests.

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_portfolio_command.py -q
# Restart TradeBot, then in Discord: TradeBot -portfolio
```
