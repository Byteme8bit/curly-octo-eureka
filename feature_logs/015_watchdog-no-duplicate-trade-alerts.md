# 015 — Stop WatchDog duplicate trade Discord alerts

**Requested:** 2026-05-25
**Status:** ✅ complete — verified 2026-05-25 (`pytest tests/test_watchdog_receipts.py` → 2 passed in 0.34s)

## Request
> TradeBot and WatchDog are duplicating their chat messages about trades. I don't need both reporting the same thing. WatchDog is only there to help control TradeBot from being too risky or losing too much too quickly or encountering errors.

## Root cause
Both bots posted on every trade receipt:
- **TradeBot** — `engine._notify_discord_trades()` → `**Trade executed**`
- **WatchDog** — `_check_receipts()` → `_trade_alerts()` → `**Watchdog — trade executed**`

## Actions taken
- **`watchdog/engine.py`**
  - Removed `_trade_alerts()` Discord message generation.
  - Added `_record_trade_from_receipt()` — increments `trades_session` for health scoring only.
  - `_check_receipts()` still parses new receipts but returns no trade alerts.
  - Startup message no longer lists "trades" under WatchDog alerts.
- **`tests/test_watchdog_receipts.py`** — 2 tests confirming receipts update session trade count without Discord alerts.

## What WatchDog still alerts on
- Trade-bot errors (with pin policy)
- Circuit breaker / re-evaluation mode
- Drawdown warnings
- Major portfolio PnL milestones
- Stale bot / diagnostics issues
- Heartbeat status
- Auto-pause on error bursts

## What TradeBot still posts
- Every trade execution (`**Trade executed**`, pinned when gain/loss exceeds threshold)
- Portfolio/strategy status on command
- Startup pin on reset

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_watchdog_receipts.py -v
```

Live: after restart, the next trade should produce **one** Discord message from TradeBot only.
