# 048 — Real-time verify tags + quiet Discord

**Requested:** 2026-06-12
**Status:** awaiting verification — pytest pending
**Branch:** `feature/048-realtime-verify-quiet-discord`
**Request-ID:** 048

## Request

Keep independent verifier (CLI + `WatchDog -verify`) but also verify each TradeBot
action in real-time and tag Discord trade messages with live-viability footer.
Reduce Discord chatter: fewer heartbeats, whale-follow skips to file only,
hourly TradeBot summaries, major market moves, quieter WatchDog/Auditor.

## Actions taken

- `bot/verifier/live_tag.py` — fast per-trade checks (market, Kraken ticker,
  fee/preflight, multi-hop → UNCERTAIN); footer strings for Discord.
- Wired into `_notify_discord_trades` and whale-follow execution posts.
- `bot/discord_summary.py` — hourly activity buffer + major-move tracker.
- `bot/whale_follow_log.py` — `logs/whale_follow_skips.log` append/read.
- Config: `DISCORD_QUIET_MODE`, granular flags, `TRADE_VERIFY_*`, move thresholds.
- Commands: `TradeBot -summary`, `TradeBot -skips`, `WatchDog -whale-skips`.
- WatchDog quiet: suppress routine heartbeats + startup spam when quiet.
- Auditor quiet: skip scheduled/event Discord posts unless proposals or over-cap.
- News v1: major price moves only; headline fetch remains Auditor-only (RSS).

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_live_verify_tag.py tests/test_quiet_discord.py tests/test_verifier.py tests/test_discord_commands.py -q
```

Restart TradeBot after deploy so `.env` quiet settings load.
