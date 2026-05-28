# Tick lifecycle

What happens in `TradingEngine.tick()` each `POLL_INTERVAL` (default 15 s).

```text
1. Fetch market data
   ├── usd_prices ............ KrakenData.fetch_usd_prices(assets)
   ├── candles ............... KrakenData.fetch_all_candles()
   └── context ............... multi-TF candles + cross-pair prices

2. Update portfolio + risk
   ├── portfolio_value ....... PaperBroker.portfolio_value(usd_prices)
   ├── governor.update_growth(portfolio)
   ├── risk.update_portfolio(portfolio)
   │     └── hibernate if drawdown >= 15% (timed mode)
   └── circuit_breaker.check(portfolio)
         └── set reevaluation_mode if drawdown >= 15% (circuit-breaker mode)

3. Adaptive alert
   └── if just entered adaptive idle mode -> Discord notice

4. Evaluate strategies
   └── StrategyOrchestrator.evaluate()
         ├── runs each plugin (cross_momentum, stat_arb, triangular_arb)
         ├── merges signals, sizes, reasons
         └── ranks intents by edge (adaptive boost for non-dominant)

5. Apply constraints + governance
   ├── constraints.trim_overweight_intents()  -> prepend defensive trims
   ├── circuit_breaker.defensive_intents()    -> prepend if reevaluation
   └── governor.apply(intents)                -> stickiness + exploration

6. Execute intents (one max per tick)
   FOR each intent in ranked order:
     ├── markets.find_path(from, to)              -> route
     ├── constraints.validate_intent(...)         -> ETH/alt gate
     ├── preflight.validate(net, fees, slippage)  -> reject losing trades
     ├── risk.approve_action(edge, usd, hops)     -> cooldown + leader gate
     ├── broker.execute_path(route, ...)          -> simulated trade
     └── governor.record_trade(strategy, ...)
         risk.record_trade()
         BREAK (one trade per tick)

7. Build status + post
   ├── build_status_snapshot(result, trades, blocked)
   ├── display.tick_status(...) -> terminal
   ├── trade_log.log(...)       -> rotating log file
   ├── discord.post_status(...) -> if changed
   └── discord notifications for trades, milestones, hibernation

8. Watchdog (separate daemon thread)
   Every poll_seconds (10 s default):
     ├── parse new runtime.log -> categorize errors (bot vs watchdog)
     ├── parse new session logs -> portfolio snapshots
     ├── parse new receipts     -> trade events
     ├── load paper_state       -> reevaluation, hibernating, baseline
     ├── parse diagnostics      -> circuit breaker dumps
     ├── stale check            -> alert if no activity > 5 min
     ├── heartbeat              -> every 15 min, always posted
     └── auto-pause             -> if score drops below threshold
```

## Timing budget

| Stage | Typical | Worst case |
|-------|---------|------------|
| Market fetch (parallel, 16 USD pairs + multi-TF) | 1.5–3 s | 12 s (with retries) |
| Strategy evaluation | 50–200 ms | 500 ms |
| Constraint + governor + risk gates | < 10 ms | 50 ms |
| Execute single trade | 0 (paper) | 100 ms |
| Discord posts (async-ish) | 200–500 ms | 5 s |
| Logging + status build | < 50 ms | 200 ms |

Tick aims to finish well under the 15 s poll interval. If it overruns, the loop just runs back-to-back without sleeping.

## Failure modes and recovery

| Failure | Behavior |
|---------|----------|
| Kraken timeout | Retry up to 2× with backoff; fall back to cached prices for that symbol |
| Single strategy raises | Caught by orchestrator; other strategies continue; error added to `blocked` |
| Trade execution fails | Logged, intent skipped, loop continues to next intent in ranking |
| Discord post fails | Warning logged; tick continues |
| Watchdog poll fails | Logged; per-check try block prevents whole-poll failure |
| Drawdown ≥ 15% | Circuit breaker engages; only defensive sells allowed until `resume-trading` |
| 3+ idle relaxation attempts | Adaptive suspended; restore strict thresholds until next trade or `reset` |

## Shutdown sequence

`TradingEngine.shutdown()`:

```
1. runtime.request_shutdown()              -> main loop exits cleanly
2. watchdog.stop()                          -> sets stop event + engine.request_stop()
   └── watchdog poll_once() checks flag between checks/alerts, joins in 5 s
3. discord.stop()                           -> Discord listener thread joins
```

Daemon threads are killed by the OS if any of the above hangs past their join timeout.
