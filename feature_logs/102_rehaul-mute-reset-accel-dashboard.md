# 102 — Rehaul: mute Discord, screenshot reset, accel B, dashboard auth

**Requested:** 2026-08-14 15:29 PDT
**Status:** complete

## Request
PERMISSION GRANTED: mute discord + reset paper to screenshot + dashboard auth refresh + accelerated option B

## Actions taken
VPS only:
- `DISCORD_QUIET_MODE=1`, `WATCHDOG_QUIET_MODE=1`, `AUDITOR_DISCORD_QUIET=1` (tokens/`DISCORD_ENABLED=1` kept)
- Paper reset to Kraken screenshot: ETH `0.49501`, USD `415.90`, ADA `24.620422`, KFEE `881.92`; trades cleared; baseline ~`$1349.04`
- Archive: `archive/2026-08-14-rehaul-screenshot-accel/`
- Accelerated option B (live stress, **not** 7-day replay): `POLL_INTERVAL=3`, `MIN_TRADE_EDGE=0.0018`, `CRYPTO_MIN_TRADE_EDGE=0.0018`, `STAT_ARB_ZSCORE_THRESHOLD=0.9`
- Dashboard: restarted `tradebot-dashboard.service`; refreshed nginx basic auth via `deploy/nginx/set_basic_auth.py`

## Verification
```powershell
ssh -F NUL -i $env:USERPROFILE\.ssh\cursor_vps root@172.245.39.184 "systemctl is-active tradebot tradebot-dashboard; python3 -c \"import json;print(json.load(open('/home/cursor/eth-trading-bot/.paper_state.json'))['balances'])\""
```
Open https://lynch.gdn/tradebot/ with new basic-auth creds from agent reply / `logs/.dashboard_basic_auth`.

## Notes
True 7-day→1–2h compression is not supported; option B is a faster live paper stress window. Re-enable Discord with quiet flags `=0`.
