# 016 — Fix Gain/Loss always showing $0.00 (entry)

**Requested:** 2026-05-25
**Status:** ✅ complete — verified 2026-05-25 (`pytest tests/test_trade_log.py` → passed)

## Request
> The Gain/Loss metric always says $0.00 (entry) why?

## Root cause (two bugs)
1. **`pnl_label()`** returned `"$0.00 (entry)"` for **every** `side == "buy"` trade, ignoring the actual `gain_loss` value.
2. **`paper_broker._execute_leg()`** set `gain_loss: 0.0` on all buy legs, including **cross-coin swaps** (e.g. ETH → AAVE) where immediate USD mark-to-mark PnL should reflect fees/slippage.

Most rotation trades are cross buys, so Discord always showed `(entry)`.

## Actions taken
- **`bot/trade_log.py`**
  - `pnl_label()` now checks `gain_loss` first; `(entry)` only for USD buys with zero realized PnL.
  - Cross swaps at exactly $0 show `(swap)` instead of `(entry)`.
  - Added `pnl_label_for_trade(trade)` helper used by alerts/receipts/terminal.
- **`bot/paper_broker.py`**
  - Cross buys compute `gain_loss = to_usd - from_usd` at execution (typically a small fee-driven loss).
- **`bot/report.py`**, **`bot/display.py`** — use `pnl_label_for_trade`.
- **`tests/test_trade_log.py`** — 6 unit tests.

## Expected after fix
- ETH → AAVE cross swap: `Gain/Loss: -$0.25 (loss)` (approx fee drag) instead of `$0.00 (entry)`.
- USD → ETH first purchase: still `$0.00 (entry)`.
- Sell with profit: `+$1.58 (profit)` unchanged.

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_trade_log.py -v
```

Restart bot; next cross swap trade should show a real fee-based loss (or profit if arb edge exceeds fees).
