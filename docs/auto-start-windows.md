# Windows auto-start (Task Scheduler)

TradeBot can restart automatically after a reboot using a lightweight **Windows
Task Scheduler** job — no full Windows Service registration required.

## Why logon, not boot?

The registered task uses an **At logon** trigger for the current Windows user,
not **At system startup**.

| Trigger | Fits TradeBot? |
|---------|----------------|
| **At logon** (chosen) | Repo, `.env`, and venv live under your user profile; the bot runs in your interactive session after you sign in. |
| At system startup | Runs before logon in session 0; often needs stored credentials, and paths under `%USERPROFILE%` may not be ready. |

If the PC reboots overnight and you have auto-logon enabled, the task still
fires at logon. If you sign in manually, TradeBot starts then.

## One-time setup

From the repo root in PowerShell (admin **not** required for your own user):

```powershell
# TradeBot only
powershell -ExecutionPolicy Bypass -File .\scripts\register_tradebot_task.ps1

# TradeBot + local dashboard (recommended after reboot)
powershell -ExecutionPolicy Bypass -File .\scripts\register_tradebot_task.ps1 -IncludeDashboard
```

Verify:

```powershell
schtasks /Query /TN "TradeBot-AutoStart" /V /FO LIST
schtasks /Query /TN "TradeBot-Dashboard-AutoStart" /V /FO LIST   # when -IncludeDashboard used
```

Manual test (safe — skips if already running):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_tradebot.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start_dashboard.ps1
```

## What the task does

1. **`scripts/start_tradebot.ps1`** runs at logon.
2. **`scripts/is_tradebot_running.py`** checks `tradebot.lock` with the same PID
   logic as `bot.singleton` (including Windows-safe liveness).
3. If a live instance exists → exit 0, no duplicate.
4. If the lock is stale (dead PID) → remove lock, then start.
5. **`main.py`** acquires the singleton lock again as a second guard.
6. Process is detached; stdout/stderr append to:
   - `logs/bot_stdout.log`
   - `logs/bot_stderr.log`
7. Launcher actions are logged to `logs/autostart.log`.

Task Scheduler **restart on failure** (3 attempts, 1 minute apart) applies to
the launcher script if startup fails — not to crashes inside the long-running
bot process.

## Remove the task

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\unregister_tradebot_task.ps1
```

## Dashboard auto-start

TradeBot and the local dashboard are separate processes. Register both at logon
with `-IncludeDashboard`:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\register_tradebot_task.ps1 -IncludeDashboard
```

This creates a second task, **`TradeBot-Dashboard-AutoStart`**, that runs
`scripts/start_dashboard.ps1`. The launcher skips startup when port
`DASHBOARD_PORT` (default **8765**) is already listening. Logs:

- `logs/dashboard_autostart.log` — launcher actions
- `logs/dashboard_stdout.log` / `logs/dashboard_stderr.log` — process output

Remove both tasks:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\unregister_tradebot_task.ps1 -IncludeDashboard
```

## Equivalent `schtasks` command

`register_tradebot_task.ps1` is preferred (sets restart policy and working
directory). Manual equivalent:

```powershell
schtasks /Create /TN "TradeBot-AutoStart" /SC ONLOGON /RL LIMITED /F `
  /TR "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"C:\Users\lynch\eth-trading-bot\scripts\start_tradebot.ps1`""
```

Replace the path with your repo root.

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Task exists but bot did not start | `logs/autostart.log`, `logs/bot_stderr.log` |
| "already running" after crash | Delete stale `tradebot.lock` or run `start_tradebot.ps1` (removes stale lock automatically) |
| venv missing | Run `python -m venv .venv` and `pip install -r requirements.txt` |
| Task not listed | Re-run `register_tradebot_task.ps1` |
