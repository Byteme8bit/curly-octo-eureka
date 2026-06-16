# 066 — Fix live losses + auditor double post

**Requested:** 2026-06-15
**Status:** awaiting verification — pytest pending

## Request
Tradebot executing live trades that lose money; Auditor double-posts on `au -review`.

## Root causes
- **Live losses:** 4-leg triangular mirror routes (`ETH->UNI->USD->ATOM->ETH`) passed paper
  preflight (+5% est net) but lost ~$2 each live. `LIVE_MAX_USD_PER_TRADE` was re-applied on
  legs 2–4, stranding inventory (e.g. leg1 bought 26.4 UNI, leg2 sold only 25.0). Env had
  `LIVE_MAX_ROUTE_LEGS=4` despite 4-leg loops being unsafe on Kraken sequential fills.
- **Auditor dedupe:** `AuditorService._post_summary_to_discord` posts summary + attachment, then
  `engine._handle_auditor_command` returned the same summary and `discord_bot.send_reply` posted
  again.

## Actions taken
- `bot/live_broker.py` — apply `LIVE_MAX_USD_PER_TRADE` cap only on route leg 1; continuation
  legs use full intermediate balances.
- `bot/engine.py` — `_live_mirror_offensive_block` under `LIVE_STRICT_PROFIT` / profit-only:
  block net ≤ floor, 4+ leg offensive routes, multi-hop slippage cushion. Manual auditor
  commands return `""` so Discord gets one post from the service layer.
- `.env` — `LIVE_MAX_ROUTE_LEGS=3` (local, not committed).
- Tests in `test_live_broker.py`, `test_profit_only_mode.py`, `test_auditor.py`.

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_live_broker.py tests/test_profit_only_mode.py tests/test_auditor.py -q
.\scripts\start_tradebot.ps1
```

## Notes
- Defensive / loss-mitigation trades (e.g. cross_momentum trim with negative edge) still mirror
  by design — preflight bypass for `is_defensive`.
- Paper triangular arb may still run 4-hop; live mirror blocks ≥4 legs when strict profit on.
