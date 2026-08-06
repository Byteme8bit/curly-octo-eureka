# VPS deploy — TradeBot + dashboard

**Target:** `mail.lynch.gdn` (`cursor@172.245.39.184`)  
**Access model:** dashboard binds `127.0.0.1:8765`; public URL via nginx:

**https://lynch.gdn/tradebot/** (HTTP basic auth)

## One-shot from Windows

```powershell
.\scripts\deploy_to_vps.ps1
```

## Dashboard access

- Public: https://lynch.gdn/tradebot/
- Creds file on VPS: `/home/cursor/eth-trading-bot/logs/.dashboard_basic_auth` (not in git)
- Reset auth: `python3 deploy/nginx/set_basic_auth.py` on VPS
- SSH tunnel fallback:

```powershell
ssh -F NUL -i $env:USERPROFILE\.ssh\cursor_vps -L 8765:127.0.0.1:8765 cursor@172.245.39.184
```

## Service control (on VPS)

```bash
sudo systemctl status tradebot tradebot-dashboard
sudo systemctl restart tradebot
sudo journalctl -u tradebot -f
```

## Notes

- Paper-only profile + real Kraken public fees (~0.40%).
- Do not run a second paper bot on Windows while VPS is active.
- `.env` is copied over SSH and never committed.
