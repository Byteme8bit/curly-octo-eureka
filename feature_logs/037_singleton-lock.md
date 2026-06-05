# Feature 037 — Singleton PID-lock guard

**Date:** 2026-06-05
**Branch:** `feature/037-singleton-lock`
**Request-ID:** 037

## Problem

Multiple TradeBot instances were running simultaneously — confirmed by 4 Discord
responses to a single command.  The user had to hard-shutdown their PC to
recover.

### Root causes identified

1. **Multiple Cursor agent sessions (primary).**  Each Cursor chat session
   (diagnosis agents, maintenance automation, ad-hoc user-directed agents)
   independently launched `main.py` without first checking whether an instance
   was already running.  There was zero enforcement preventing this.

2. **Windows `os.execv` zombie parent (secondary / architectural).**  When the
   Auditor self-restart path fires (`_perform_self_restart()` → `os.execv()`),
   Python on Windows *spawns a child process* instead of replacing the current
   one (unlike POSIX).  The original venv-launcher process stays alive
   alongside the child.  Each self-restart therefore leaks one extra process.
   (Note: `AUDITOR_AUTOAPPLY_ENABLED=0` so this path was not actively firing,
   but the design flaw remained.)

3. **No singleton guard (enabling condition).**  Nothing in `main.py` prevented
   a second invocation while one was already running.

### What was ruled out

- **Task Scheduler:** Only `KrakenMonitor-Daily` runs Python and it runs
  `scripts/monitor_kraken_changes.py`, never `main.py`.
- **Startup entries / Registry Run keys:** None reference `main.py` or the bot.
- **Wrapper/launcher scripts:** No `.ps1`, `.bat`, `.cmd`, or `.sh` files
  outside `.venv` found.
- **`automation/maintenance_prompt.md`:** Already contains the hard rule
  "Never restart the user's bot process. Never schedule additional
  automations." — the maintenance agent is not implicated.
- **Crash-recovery loop:** The main loop in `engine.run()` catches per-tick
  exceptions but does not restart the process.

## Solution — PID-file singleton lock

### New file: `bot/singleton.py`

`acquire_lock(take_lock=False)`:
- Reads `tradebot.lock` (repo root) if it exists.
- If the recorded PID maps to a **live** process and is **not** the current
  PID: prints a clear error to stderr and calls `sys.exit(1)`.
- Otherwise writes the current PID to the lock file.
- `take_lock=True` bypasses the liveness check and forcefully overwrites —
  used by the os.execv restart path on Windows.

`release_lock()`:
- Deletes the lock file on clean shutdown; silently ignores a missing file.

### Modified: `main.py`

- Calls `acquire_lock(take_lock="--take-lock" in sys.argv)` at the very top of
  `_run()`, before any heavy imports.
- Strips `--take-lock` from `sys.argv` so it is invisible to the engine.
- In the `finally` block, calls `release_lock()` only when
  `engine._restart_requested` is False (i.e. clean exit, not a self-restart).

### Modified: `bot/engine.py` — `_perform_self_restart()`

- The argv passed to `os.execv` now always includes `--take-lock`.
- Any pre-existing `--take-lock` in `sys.argv` is stripped first to avoid
  duplicates.

### Modified: `.gitignore`

- `tradebot.lock` added (runtime file, must never be committed).

### Windows os.execv restart flow (after fix)

```
Process A (PID 100)  →  lock file: "100"
  Auditor triggers restart
  _perform_self_restart() → os.execv([python, main.py, --take-lock])
    Process B (PID 200) spawned — sees --take-lock → overwrites lock: "200"
    Process A continues briefly (Windows zombie), then exits
  Lock file: "200"  ← only Process B is the legitimate owner
```

Any subsequent start attempt (without `--take-lock`) sees PID 200 is alive →
**blocked**.

## Tests

New file: `tests/test_singleton.py` — 9 tests covering:

| Test | Scenario |
|------|----------|
| `test_acquire_lock_creates_lock_file` | No lock → file created with current PID |
| `test_acquire_lock_stale_pid_succeeds` | Stale lock (dead PID) → overwritten |
| `test_acquire_lock_live_duplicate_exits` | Live duplicate → `SystemExit(1)` |
| `test_acquire_lock_take_lock_overwrites_live_pid` | `take_lock=True` bypasses check |
| `test_acquire_lock_own_pid_succeeds` | Same PID in lock → allowed |
| `test_release_lock_removes_file` | Lock file deleted on release |
| `test_release_lock_missing_file_is_safe` | No lock file → no error |
| `test_acquire_lock_corrupt_content_is_treated_as_stale` | Corrupt file → treated as stale |
| `test_pid_is_running_current_process` | Current PID is alive |
| `test_pid_is_running_dead_pid` | PID 0 is not signal-able |

## Files changed

| File | Change |
|------|--------|
| `bot/singleton.py` | New — PID lock implementation |
| `main.py` | Modified — acquire/release lock, handle `--take-lock` flag |
| `bot/engine.py` | Modified — inject `--take-lock` into os.execv restart argv |
| `.gitignore` | Modified — add `tradebot.lock` |
| `tests/test_singleton.py` | New — 9 unit tests |
| `feature_logs/037_singleton-lock.md` | New — this file |

## Version history snapshots (request-id 037)

- `main.py` r002
- `bot/engine.py` r008
- `.gitignore` r002
