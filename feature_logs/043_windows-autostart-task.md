# 043 — Windows autostart scheduled task

**Requested:** 2026-06-10
**Status:** complete (pytest passed locally; task registered on user PC)
**Branch:** `feature/043-windows-autostart-task`
**Request-ID:** 043

## Request

> seems like my computer may have rebooted. Can we create a scheduled task that
> auto runs as a service TradeBot for instances like this?

## Actions taken

- `scripts/is_tradebot_running.py` — exit 0/1 helper reusing `bot.singleton`
  `_pid_is_running` for consistent pre-flight checks.
- `scripts/start_tradebot.ps1` — singleton-aware launcher; stale lock removal;
  detached start with stdout/stderr to `logs/bot_stdout.log` /
  `logs/bot_stderr.log`; wrapper log at `logs/autostart.log`.
- `scripts/register_tradebot_task.ps1` — registers `TradeBot-AutoStart` with
  **At logon** trigger (current user), Interactive/Limited principal, restart 3×
  at 1-minute intervals on launcher failure.
- `scripts/unregister_tradebot_task.ps1` — removes the task.
- `docs/auto-start-windows.md` — setup, trigger rationale, troubleshooting,
  optional dashboard note.
- `README.md`, `docs/README.md` — links to auto-start doc.
- `tests/test_is_tradebot_running.py` — minimal unit tests for running helper.

### Trigger choice

**At logon** (not At system startup): desktop machine; repo and `.env` under
user profile; no admin password storage required.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_is_tradebot_running.py tests/test_singleton.py -q
powershell -ExecutionPolicy Bypass -File .\scripts\register_tradebot_task.ps1
schtasks /Query /TN "TradeBot-AutoStart" /V /FO LIST
powershell -ExecutionPolicy Bypass -File .\scripts\start_tradebot.ps1
```

## Notes

- Does not register the task in CI.
- Dashboard auto-start documented as optional second task; not registered by default.
