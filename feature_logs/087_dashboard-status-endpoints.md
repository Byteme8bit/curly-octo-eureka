# 087 — Dashboard status health endpoints

**Requested:** 2026-08-05
**Status:** complete

## Request
Fix dashboard verification after connection refused; `/api/paper/status` returned 404.

## Actions taken
- `dashboard/app.py` — add `/api/status`, `/api/paper/status`, `/api/live/status` lightweight health checks

## Verification
```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/paper/status
```
Expect `{"ok": true, "mode": "paper", ...}`.

## Notes
Dashboard must be started separately via `scripts/start_dashboard.ps1`; does not auto-start with TradeBot.
