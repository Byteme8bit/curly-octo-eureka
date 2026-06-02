# 033 — Fix display stdout OSError on background runs

**Requested:** 2026-06-02
**Status:** complete

## Request
Fix runtime errors and restart the bot so Auditor chat proposals work (`Auditor -ask` →
`-list` → `-confirm`). Bot was on `main` (~`f409d15`) with PR #23/#25 merged.

## Actions taken
- Root cause: `OSError: [Errno 22] Invalid argument` from colorama flushing stdout
  when the bot runs in a Cursor-captured background terminal (`display.tick` →
  `print()`). Every ~25s tick logged `Tick failed` / `Market tick` though trading
  continued.
- `bot/display.py`: `_safe_print()` swallows broken stdout; skip colorama `init` when
  stdout is not a TTY.
- `tests/test_startup_display.py`: regression test for broken stdout during `tick()`.

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_startup_display.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe .\scripts\verify_main_startup.py
```
Restart `main.py` on `origin/main` after merge; confirm no recurring `Tick failed` in
`logs/runtime.log`. Discord: `Auditor -ask audit portfolio and make a proposal` →
`-list` → `-confirm <id>`.

## Notes
Transient Discord HTTP 503 and Kraken timeouts are self-healing — not changed here.
