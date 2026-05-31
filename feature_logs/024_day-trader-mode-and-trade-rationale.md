# 024 — Day-trader mode + rich trade rationale (Phase 1)

**Requested:** 2026-05-30
**Status:** awaiting verification — pytest passing locally (266), live Discord smoke test pending

## Request
> Make it act like a day trader who knows exactly what they are doing — watching
> the crypto markets live, making trades, and posting to Discord *why* it made
> THAT trade (mitigating losses vs. going for growth). Let's make some money.

Scoping decisions (via questionnaire):
- **Money mode:** keep PAPER while we sharpen it, graduate to real later.
- **Instruments:** all of the above — spot (now), perpetual futures (Phase 2),
  options/calls-puts (Phase 3).
- **Risk appetite:** aggressive.

This is **Phase 1** of a multi-phase build. Phases 2 (perp futures sim with
leverage + shorting) and 3 (options sim with Black-Scholes + Greeks) are tracked
as follow-ups.

## What shipped in Phase 1

### 1. Rich trade rationale in Discord + receipts (`bot/trade_log.py`, `bot/report.py`, `bot/engine.py`)
The headline ask: every fill now explains its intent.
- `classify_trade(trade)` → human label answering "loss-mitigation or growth?":
  `LOSS-MITIGATION (defensive de-risking)`, `PROFIT-TAKING (locking in a gain)`,
  `LOSS-MITIGATION (cutting a losing position)`, `GROWTH (opening a new position)`,
  `REBALANCE (rotating into stronger momentum)`, `GROWTH (adding to a position)`.
- `trade_rationale(trade)` → multi-line "why" block: intent class + which strategy
  fired + expected edge (`%`) + the underlying signal reason.
- The engine now carries the intent's `edge`, `gross_return_pct`, `is_defensive`,
  `is_expansion`, `is_held_swap` onto the executed-trade dict so the rationale and
  the saved receipt both have the context (previously dropped at execution).
- `format_trade_executed_alert` inserts the rationale block into the Discord alert.

### 2. Aggressive "Day-Trader Mode" profile (`config.py`)
Opt-in `DAY_TRADER_MODE=1` flips the *defaults* of the cadence/sizing knobs
(explicit env vars still override). Edges stay fee-protected by preflight, so
"aggressive" means more/larger trades, not unprofitable ones.

| Knob | Normal default | Day-trader default |
|---|---|---|
| `TRADE_SIZE_PCT` | 0.10 | 0.20 |
| `TRADE_COOLDOWN_SECONDS` | 180 | 45 |
| `MAX_TRADES_PER_HOUR` | 12 | 40 |
| `MIN_TRADE_EDGE` | 0.006 | 0.004 |
| `LEADER_STABLE_SECONDS` | 600 | 120 |

(`POLL_INTERVAL` is already 15s, so the loop is already watching live.)

### 3. Restored `MIN_ETH_RESERVE` default 0.5 → 0.25
Undoes the unrequested change from request 023 that was tightening how much the
bot could trade — back to the pre-this-morning behavior.

## Files changed
- **Modified** `bot/trade_log.py` — `classify_trade`, `_edge_str`, `trade_rationale`.
- **Modified** `bot/report.py` — import + insert rationale into the trade alert.
- **Modified** `bot/engine.py` — attach intent context to executed-trade dict.
- **Modified** `config.py` — `DAY_TRADER_MODE` profile; `MIN_ETH_RESERVE` default back to 0.25.
- **Modified** `tests/test_trade_log.py` — 7 new tests for classification + rationale.

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest -q          # 266 passing locally
```
Live smoke test (on the bot host): set `DAY_TRADER_MODE=1` in `.env`, restart,
and confirm the next executed trade posts a "Why:" block to Discord.

## Next (not yet built)
- **Phase 1b:** sharper intraday momentum/breakout entries+exits; hard daily
  loss-cap rail (`DAILY_LOSS_CAP_PCT`) so aggressive ≠ reckless.
- **Phase 2:** perpetual-futures simulation — leverage + shorting, margin and
  liquidation modeling in the paper broker.
- **Phase 3:** options simulation — calls/puts via Black-Scholes, strikes/expiries, Greeks.
