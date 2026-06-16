# 069 — Fix live errors (TSLAx, route halt, force edge)

**Requested:** 2026-06-16
**Status:** awaiting verification — pytest pending

## Request
Discord failures: TSLAx mirror spam, UNI/BTC leg-2 insufficient funds LIVE HALT,
force trade blocked on +0.2% net by swap hurdle, bot stuck halted.

## Actions taken
- **Modified** `bot/equities.py` — `filter_equity_watchlist()` for Kraken validation.
- **Modified** `config.py` — skip missing xStocks from watchlist + `LIVE_ALLOWED_ASSETS`.
- **Modified** `bot/live_broker.py` — sequential route preflight + chain leg sizing.
- **Modified** `bot/risk.py` — multi-hop uses min-net gate, not swap hurdle.
- **Modified** `bot/engine.py` — `-resume-live`, scan activity line, route halt clear.
- **Modified** `bot/discord_bot.py` — `resume-live` command alias.
- **Modified** `bot/discord_summary.py` — `format_tick_activity_line` (feature 068 merge).
- **Added** tests for equity skip, route preflight, multihop force edge, resume-live.

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_equity_validation.py tests/test_live_route_preflight.py tests/test_force_multihop_edge.py tests/test_resume_live_halt.py tests/test_tick_activity_line.py tests/test_force_command.py -q
.\scripts\start_tradebot.ps1
```
Discord: `TradeBot -resume-live` then `TradeBot -portfolio` / `TradeBot -force`.
