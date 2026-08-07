# 096 — Dashboard trade count + closed-loop PnL

**Requested:** 2026-08-07 03:34 PDT
**Status:** complete

## Request
User still only sees 15 trades and no arbitrage on the dashboard.

## Root cause
1. Dashboard `trade_count` was `len(recent_receipts)` with **limit=15** — always capped at 15
2. Triangular arb *was* running (ETH→BTC→ADA→ETH) but listed as `ETH->ETH` without strategy label
3. Multi-hop `gain_loss` summed per-leg cost-basis deltas → huge fake PnL on closed loops

## Actions taken
- `dashboard/parsers/tradebot.py` — true trade count from `.paper_state.json`; recent list 50; show `[strategy] path`
- `bot/paper_broker.py` — closed-loop PnL = `(end_qty - start_qty) * usd`
- `bot/live_broker.py` — pass `usd_prices` into combine helper
- Deploy dashboard + brokers to VPS; restart services

## Verification
Dashboard overview trade_count should match `len(paper_state.trades)`. New triangular receipts should show ~edge dollars, not ~notional.
