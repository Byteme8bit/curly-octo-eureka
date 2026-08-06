# 089 — VPS deploy TradeBot + dashboard

**Requested:** 2026-08-06
**Status:** complete

## Request
Publish dashboard and bot to VPS (`mail.lynch.gdn`), paper-only, dashboard via SSH tunnel; stop local Windows bot after VPS is up.

## Actions taken
- Branch `cb/vps-deploy`
- Added `deploy/systemd/tradebot.service`, `tradebot-dashboard.service`
- Added `scripts/deploy_to_vps.ps1`, `deploy/README.md`
- Deploy target: `cursor@172.245.39.184`, app dir `/home/cursor/eth-trading-bot`
- Dashboard forced to `127.0.0.1:8765`

## Verification
```powershell
.\scripts\deploy_to_vps.ps1
ssh -F NUL -i $env:USERPROFILE\.ssh\cursor_vps cursor@172.245.39.184 "sudo systemctl status tradebot tradebot-dashboard"
ssh -F NUL -i $env:USERPROFILE\.ssh\cursor_vps -L 8765:127.0.0.1:8765 cursor@172.245.39.184
# http://127.0.0.1:8765/api/paper/status
```

## Notes
VPS has ~1 GB RAM (mail server). Services capped via `MemoryMax`.
