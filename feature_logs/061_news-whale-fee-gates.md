# 061 — News, whale, and fee decision stack

**Requested:** 2026-06-15
**Status:** awaiting verification — pytest pending

## Request
Consult news and market flow before offensive trades; match whale moves when
profitable after fees; keep PROFIT_ONLY_MODE + fee floors on every path.

## What was already there
- Whale watch + whale follow with cooldown, preflight, and `WHALE_FOLLOW_MIN_NET_PROFIT`
- `PROFIT_ONLY_MODE`, `MIN_NET_PROFIT_PCT`, preflight on all offensive paths
- Crash hold, circuit breaker, defensive trims
- News fetch for Auditor reports only (not on trade path)

## What changed
- `bot/trade_context.py` — news + market-flow snapshot; gates offensive intents
- `bot/engine.py` — refresh each tick; block in tick loop + `_try_execute_intent`
- `config.py`, `.env.example`, `.env` — `TRADE_*` knobs; enable whale watch/follow
- `docs/live-trading.md` — decision stack section
- `tests/test_trade_context.py`

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_trade_context.py tests/test_whale_follow.py tests/test_profit_only_mode.py tests/test_fee_gate.py -q
```

## Notes
- DCA bypasses news/flow gates unless `TRADE_NEWS_BLOCK_DCA=1`
- Whale-follow bypasses news/flow (whale IS the flow signal) but still passes fee rails
- Triangular arb unchanged — `effective_min_net_profit()` + preflight on every hop
