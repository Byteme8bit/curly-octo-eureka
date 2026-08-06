# 086 — Re-enable Discord notifications (paper revival)

**Requested:** 2026-08-05
**Status:** blocked — awaiting Discord credentials in `.env`

## Request
Hook paper bot back up to Discord notifications.

## Actions taken
Updated `.env` (local, not committed):
- `DISCORD_ENABLED=1`
- Paper profile: `DISCORD_QUIET_MODE=0`, heartbeat 60m, immediate trade posts, major-move 3%
- `WHALE_WATCH_DISCORD_ALERTS=0` (whale detections stay in log file)

User must fill:
- `DISCORD_WEBHOOK` and/or `DISCORD_BOT_TOKEN` + `DISCORD_CHANNEL_ID`
- `DISCORD_ALLOWED_USER_IDS` (your Discord user id for `TradeBot -portfolio` etc.)

## Verification
```powershell
.\.venv\Scripts\python.exe check_discord.py
.\.venv\Scripts\python.exe main.py --test-discord
.\scripts\start_tradebot.ps1
```
Expect trade alerts, 60m heartbeats, errors (cooldown), and command replies.

## Notes
Without webhook or bot token + channel, posts are no-ops (`can_post_status` false). Never commit `.env`.
