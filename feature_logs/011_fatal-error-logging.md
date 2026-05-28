# 011 — Startup-crash logging + Error Logs folder

**Requested:** 2026-05-25 13:11 PDT
**Status:** ✅ complete — verified 2026-05-25 13:16 PDT
**Verification:** `verify_main_startup.py` → SUCCESS; `pytest tests/test_fatal_error_log.py` → 6 passed in 0.16s

## Request
> I just tried to start the bot but got huge errors (screenshot: `ModuleNotFoundError: No module named 'tzdata'` → `ZoneInfoNotFoundError: 'No time zone found with key America/Los_Angeles'`).
>
> Also ensure that when the bot encounters these types of fatal errors that prevent from launching/crashes the bot they should be logged properly so you can review them. The logs of errors should be stored in an 'Error Logs' folder please.

## Root cause of the crash
The shell launched **system Python 3.12.2** (`C:\Program Files\Python3122\...`) instead of the project venv (`C:\Users\lynch\eth-trading-bot\.venv\Scripts\python.exe`). System Python lacks `tzdata`, which Windows `zoneinfo` needs for non-UTC tz names. The venv already has `tzdata>=2024.1` in `requirements.txt`, so no dependency change needed — only an interpreter mistake.

**Fix for the user**: activate the venv before launching, or call the venv's python directly:

```powershell
cd C:\Users\lynch\eth-trading-bot
.\.venv\Scripts\Activate.ps1
python main.py
# OR (without activating)
.\.venv\Scripts\python.exe main.py
```

## Actions taken

### Fatal-error logging
- **Created `bot/fatal_error_log.py`** — minimal-import logger that writes timestamped files to `Error Logs/YYYY-MM-DD_HHMMSS_fatal.txt`. Captures: exception type/message, full traceback, Python version, interpreter path, cwd, platform, and an actionable hint.
- **Hint engine** (`_hint_for`) detects common failure modes:
  - `ModuleNotFoundError` → suggests venv activation if venv exists but isn't the running interpreter, else `pip install -r requirements.txt`
  - `ZoneInfoNotFoundError` → suggests `pip install tzdata`
  - `FileNotFoundError`, `PermissionError` → echoes the path
- **Rewrote `main.py`** — all heavy imports moved into `_run()` so they happen *after* the outer try/except. `BaseException` is caught at the top level; the file/exception/hint are printed to the terminal and the full log file path is shown.

### Tests
- **`tests/test_fatal_error_log.py`** — six tests:
  - log file is written and contains the exception
  - `Error Logs/` directory is created on first use
  - `ModuleNotFoundError` hint mentions venv or `pip install`
  - `ZoneInfoNotFoundError`-style hint mentions tzdata
  - unknown exceptions return empty hint
  - logger never raises on bad input

### Verification script
- **`scripts/verify_main_startup.py`** — smoke test that imports `main`, `bot.fatal_error_log`, and `bot.local_time`; exercises `log_fatal`; prints `SUCCESS` or each failure. Run with the venv python.

### Gitignore
- Added `Error Logs/` so crash logs stay local (often contain absolute paths and environment details).

### Archive system (added 2026-05-25 13:17 PDT)
- **`bot/fatal_error_log.py`** — added `archive_log(path, reason)` and `archive_all_logs(reason)`. Moves files into `Error Logs/archived/` with an `archived-YYYY-MM-DD_HHMMSS--<original>` prefix and appends a footer noting when/why it was archived. Never raises on filesystem errors.
- **`scripts/archive_error_logs.py`** — CLI helper:
  - `python scripts/archive_error_logs.py --list` — show loose vs archived counts
  - `python scripts/archive_error_logs.py --all --reason "..."` — archive every loose log
  - `python scripts/archive_error_logs.py "Error Logs/<file>.txt"` — archive a single log
- **3 new tests** in `tests/test_fatal_error_log.py`: archive moves + footer, missing-file no-op, batch archive moves all loose logs.
- **Handled the existing test log**: `2026-05-25_131610_fatal.txt` (the synthetic crash from the smoke test) was archived to `Error Logs/archived/archived-2026-05-25_131700--2026-05-25_131610_fatal.txt`.

## How to verify locally
```powershell
cd C:\Users\lynch\eth-trading-bot
.\.venv\Scripts\python.exe scripts\verify_main_startup.py
.\.venv\Scripts\python.exe -m pytest tests\test_fatal_error_log.py -v
```
Both should print `SUCCESS` / all green. After that, `python main.py` (with venv active) should launch normally.

## Notes
- Cursor agent shell is still sandbox-locked (feature 007) so I cannot execute these tests myself. Manual run required to flip status to `complete`.
- Per feature 010's verification convention, this stays "awaiting verification" until the user confirms.
