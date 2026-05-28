# 002 — Agile reevaluation with strategy stickiness

**Requested:** 2026-05-25
**Status:** complete

## Request
> TradeBot should stay agile constantly reevaluating coin pairs and how best to proceed. I'd like to see fairly regular trades and some experimentation by the bot but consistency is king. Dont change strats if one is working well. Monitor growth and keep current strat if growth stays consistent especially if it is strong gains.

## Actions taken
- **Created `bot/strategy_governor.py`** — `StrategyGovernor` class that:
  - Tracks portfolio growth over a rolling window (default 4h)
  - Identifies a "dominant" strategy (whichever last executed a trade)
  - Applies stickiness: keeps dominant strategy unless challenger edge > switch margin (margin doubles under strong growth)
  - Adds exploration: when growth is flat, ~1 in 4 trades can try the #2 ranked strategy
  - Persists per-strategy PnL/trade counts for visibility
- **`bot/engine.py`** — applies governor between orchestrator ranking and execution; records strategy on trade
- **`bot/paper_broker.py`** — added `dominant_strategy`, `dominant_since`, `growth_window_*`, `strategy_stats`, `total_trades` to `RiskState`; trade records now include `strategy_name`
- **`bot/orchestrator.py`** — adaptive boost extended to `cross_momentum` (was only stat_arb / triangular)
- **`bot/report.py`** — Discord `strategy` command shows dominant strategy, growth, per-strategy PnL, and policy notes
- **`config.py`** — added 5 new settings
- **`.env`** + **`.env.example`** — appended under "Strategy governance" section
- **Lowered `IDLE_REEVAL_HOURS`** from 3 to 2 for more responsive idle relaxation

## Verification
- Modules compile cleanly
- Policy decisions appear in blocked output as `Stickiness — keeping cross_momentum (strong growth +1.8%)` or `Exploration — trying stat_arb (flat growth +0.2%)`

## Notes
- Defensive intents (portfolio caps, circuit breaker) bypass the governor — they always execute regardless of stickiness.
