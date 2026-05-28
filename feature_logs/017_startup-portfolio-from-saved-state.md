# 017 — Startup banner shows saved portfolio, not config defaults

**Requested:** 2026-05-25
**Status:** awaiting verification — pytest pending

## Request
> When I restart the bot without resetting paper status, the bot always declares same initial values 1 ETH 83 ADA however it does seem to pick up where it left off.

## Root cause
`engine.run()` passed `self.settings.initial_balances` (from `.env` `INITIAL_BALANCES`) to `display.startup()`, while trading used `broker.state.balances` loaded from `.paper_state.json`.

## Actions taken
- **`bot/engine.py`** — startup banner now uses `self._holdings()` (actual saved paper state).
- **`bot/display.py`** — omits zero-balance assets from the Portfolio line for readability.
- **`tests/test_startup_display.py`** — 2 regression tests.

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_startup_display.py -v
```

Restart bot without reset — header Portfolio line should match first tick holdings (e.g. AAVE, ADA, ATOM, ETH).
