# Architecture overview

TradeBot is a single-process paper trading bot that uses live Kraken market data, a multi-strategy orchestrator with fee-aware gating, and an in-process watchdog for monitoring.

## Goals

1. **Agile** — reevaluate all symbols every 15 s, keep trades fee-positive net of slippage.
2. **Consistent** — stick with a working strategy; allow controlled experimentation when growth is flat.
3. **Safe** — enforce ETH reserve, alt allocation caps, drawdown circuit breaker, and adaptive idle relaxation.
4. **Observable** — Pacific-time logs, per-trade receipts, Discord alerts/commands, watchdog health score, local chat mirror.

## High-level diagram

```text
                       ┌────────────────────────────────────────────────┐
                       │                main.py (process)               │
                       │                                                │
   Kraken REST  ◀──────┤  KrakenData (ccxt + retry/cache)               │
                       │      │                                         │
                       │      ▼                                         │
                       │  TradingEngine.tick()  ─── every poll_interval │
                       │      │                                         │
                       │      ├── StrategyOrchestrator                  │
                       │      │      ├── cross_momentum                 │
                       │      │      ├── stat_arb                       │
                       │      │      └── triangular_arbitrage           │
                       │      │                                         │
                       │      ├── PortfolioConstraints (ETH/alt rules)  │
                       │      ├── StrategyGovernor (stickiness/explore) │
                       │      ├── PreFlightValidator (fees + slippage)  │
                       │      ├── RiskManager (gates + cooldowns)       │
                       │      ├── CircuitBreaker (drawdown protection)  │
                       │      └── PaperBroker (executes simulated path) │
                       │                                                │
                       │  ┌───────────────────────────────────────┐     │
                       │  │ Discord (webhook + bot token) thread  │ ◀───┼── chat log file
                       │  └───────────────────────────────────────┘     │
                       │                                                │
                       │  ┌───────────────────────────────────────┐     │
                       │  │ WatchdogService (daemon thread)       │ ────┼── .watchdog_state.json
                       │  │   parses runtime.log, receipts, state │     │
                       │  └───────────────────────────────────────┘     │
                       │                                                │
                       │  ┌───────────────────────────────────────┐     │
                       │  │ AuditorService (daemon thread)        │ ────┼── .auditor_state.json
                       │  │   audits trades · news · proposals    │     │   runtime_overrides.json
                       │  └───────────────────────────────────────┘     │   reports/YYYY-MM-DD/*.md
                       │                                                │
                       └────────────────────────────────────────────────┘
                                          │
                                          ▼
                          logs/ · receipts/ · .paper_state.json
```

## Process model

A single Python process owns four threads:

| Thread | Lifecycle | Purpose |
|--------|-----------|---------|
| **Main** | `python main.py` | Runs `TradingEngine.tick()` on a poll loop |
| **Discord listener** | Daemon, started by `DiscordBot.start()` | Polls Discord channel every 2 s for owner commands |
| **Watchdog** | Daemon, started by `WatchdogService.start()` | Reads logs/receipts/state every 10 s, alerts + auto-pauses |
| **Auditor** | Daemon, started by `AuditorService.start()` | 5-minute scheduler heartbeat; runs daily audits + event-triggered reviews |

All four stop together via `TradingEngine.shutdown()` (signal handler or `finally`).

## Layered responsibilities

```
┌──────────────────────────────────────────────────────┐
│  Presentation: display.py, report.py, discord_bot.py  │   formats output
├──────────────────────────────────────────────────────┤
│  Application:  engine.py, runtime.py                 │   tick loop, lifecycle
├──────────────────────────────────────────────────────┤
│  Domain:       orchestrator, strategies/, risk,      │   trading logic
│                portfolio_constraints, governor,      │
│                preflight, circuit_breaker, fee_engine│
├──────────────────────────────────────────────────────┤
│  Infrastructure: data.py (Kraken), paper_broker,     │   IO + persistence
│                  markets.py, trade_log, pin_tracker, │
│                  watchdog/                           │
└──────────────────────────────────────────────────────┘
```

## Persistence

| File | Owner | Content |
|------|-------|---------|
| `.paper_state.json` | `PaperBroker` | Balances, cost basis, trades, `RiskState` |
| `.watchdog_state.json` | `WatchdogState` | File offsets, error timestamps, dedup keys |
| `.auditor_state.json` | `AuditorState` | Pending tier-2 proposals + last-run timestamps |
| `runtime_overrides.json` | `AuditorService` / `config._apply_runtime_overrides` | User-confirmed tier-2 knob overrides (read at startup) |
| `reports/YYYY-MM-DD/audit-HHMMSS.md` | `AuditorService` | Full markdown audit reports |
| `.discord_pins.json` | `PinTracker` | Pinned message IDs for cleanup |
| `logs/runtime.log` | Python logging | Warnings/errors across all modules |
| `logs/YYYY-MM-DD_HH-00_to_*_PDT.log` | `trade_log.py` | Per-tick portfolio snapshots |
| `logs/discord_chat.log` | `DiscordChatLog` | Inbound/outbound chat audit (gitignored) |
| `receipts/*.txt` | `paper_broker` | One file per executed trade |
| `feature_logs/NNN_*.md` | Agent | Per-request engineering record |

## Configuration

All runtime knobs live in `.env` (gitignored) loaded by `config.load_settings()` into a single frozen `Settings` dataclass. See [`../conventions/patterns.md#configuration`](../conventions/patterns.md#configuration).
