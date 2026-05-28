# 022 - Cursor Cloud development environment

**Requested:** 2026-05-28 11:19 PDT
**Status:** complete - environment verified; pytest has 2 existing startup-display failures

## Request
Please set up the development environment for this codebase. Run the application(s) and demonstrate that the environment is working.

## Actions taken
- Installed Python development dependencies from `requirements-dev.txt`.
- Registered the Cursor Cloud startup dependency refresh as `python3 -m pip install -r requirements-dev.txt`.
- Documented Cursor Cloud runtime caveats in `AGENTS.md`.
- Started `python3 main.py` in a tmux session and observed a live paper-trading tick.

## Verification
- `python3 -m compileall -q bot watchdog scripts tests config.py main.py check_discord.py` passed.
- `python3 -m pytest` ran to completion with 225 passing tests and 2 existing failures in `tests/test_startup_display.py` caused by the stale `TerminalDisplay(log_writer=...)` constructor call.
- `python3 main.py` started TradeBot, WatchDog, and Auditor; Kraken market data loaded, the portfolio snapshot was written, and a paper trade receipt was created.

## Notes
- The Cloud VM has `python3` but no `python` shim.
- Discord, Gemini, and alert integrations remain optional and disabled unless configured in `.env`.
