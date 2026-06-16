# 067 — Discord force-trade command

**Requested:** 2026-06-15
**Status:** awaiting verification — pytest pending

## Request
Add `TradeBot -force` Discord command that scans for the best profitable offensive
opportunity passing all existing gates, executes on paper (mirrors to live when armed),
logs attempts to `logs/force_trade.log`, and always replies in Discord (even in quiet mode).

## Actions taken
- **Modified** `bot/discord_bot.py` — map `force` / `force-trade` tokens; help text.
- **Modified** `bot/engine.py` — `_handle_force_trade`, `_evaluate_force_intent`,
  `_force_trade_halt_reason`; respects drawdown halt, re-evaluation, profit-only, preflight.
- **Added** `bot/force_trade_log.py` — append-only file logger.
- **Modified** `config.py` — `FORCE_TRADE_LOG_FILE` (default `logs/force_trade.log`).
- **Added** `tests/test_force_command.py` — handler + parser coverage.
- **Modified** `tests/test_discord_commands.py` — parser param for `-force`.
- **Modified** `docs/live-trading.md` — brief force-command section.

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_force_command.py tests/test_discord_commands.py -q
.\scripts\start_tradebot.ps1
```
In Discord: `TradeBot -force` — expect execute or blocked reply with best edge + reason.

## Notes
- Does **not** bypass gates (unlike idle probe). Optional DCA fallback when DCA enabled
  and no offensive route clears.
- Command replies use `send_reply` and are unaffected by `DISCORD_QUIET_MODE`.
