# Module map

Every module's responsibility, public surface, and dependencies. When you add or move a module, update this file.

Legend: 🟦 application · 🟩 domain · 🟧 infrastructure · 🟨 presentation

## Top-level entry points

| Module | Role | Key entry points |
|--------|------|------------------|
| `main.py` | 🟦 Process bootstrap | `main()`, signal handlers |
| `config.py` | 🟧 Settings loader | `load_settings()`, `Settings` |
| `check_discord.py` | 🟦 Smoke test | `--check-discord` CLI |

## `bot/` — trading engine and strategies

### Application
| Module | Role | Public surface |
|--------|------|----------------|
| `bot/engine.py` | 🟦 Tick orchestration | `TradingEngine.run()`, `tick()`, `shutdown()` |
| `bot/runtime.py` | 🟦 Lifecycle flags | `BotRuntime.is_trading_active()`, `request_shutdown()` |

### Domain
| Module | Role | Public surface |
|--------|------|----------------|
| `bot/orchestrator.py` | 🟩 Merge + rank strategy outputs | `StrategyOrchestrator.evaluate()` |
| `bot/strategies/base.py` | 🟩 Strategy interface | `Strategy`, `TradeIntent`, `StrategyResult` |
| `bot/strategies/cross_momentum.py` | 🟩 Strategy plugin | `CrossMomentumStrategy` |
| `bot/strategies/stat_arb.py` | 🟩 Strategy plugin | `StatArbStrategy` |
| `bot/strategies/triangular_arbitrage.py` | 🟩 Strategy plugin | `TriangularArbitrageStrategy` |
| `bot/strategies/momentum_rotation.py` | 🟩 Strategy plugin (legacy) | `MomentumRotationStrategy` |
| `bot/strategies/registry.py` | 🟩 Strategy lookup | `build_orchestrator()`, `STRATEGY_REGISTRY` |
| `bot/risk.py` | 🟩 Trade gates + cooldowns | `RiskManager`, `TradeGate` |
| `bot/portfolio_constraints.py` | 🟩 ETH floor + alt cap | `PortfolioConstraints.validate_intent()` |
| `bot/strategy_governor.py` | 🟩 Stickiness + experimentation | `StrategyGovernor.apply()`, `record_trade()` |
| `bot/preflight.py` | 🟩 Net-positive pre-flight | `PreFlightValidator.validate()` |
| `bot/circuit_breaker.py` | 🟩 Drawdown halt | `CircuitBreaker.check()` |
| `bot/fee_engine.py` | 🟩 Fee + slippage math | `FeeEngine.compute_net()` |
| `bot/adaptive.py` | 🟩 Idle threshold relaxation | `AdaptiveStatus`, `compute_relax_factor()` |
| `bot/markets.py` | 🟩 Pair discovery + routing | `Markets.find_path()` |

### Infrastructure
| Module | Role | Public surface |
|--------|------|----------------|
| `bot/data.py` | 🟧 Kraken REST + retry | `KrakenData.fetch_ticker()`, `fetch_all_candles()` |
| `bot/paper_broker.py` | 🟧 Simulated execution | `PaperBroker.execute_path()`, `RiskState`, `PaperState` |
| `bot/trade_log.py` | 🟧 Per-tick log file rotation | `TradeLog.log()` |
| `bot/local_time.py` | 🟧 Pacific time helpers | `format_pacific()`, `PACIFIC` |
| `bot/pin_tracker.py` | 🟧 Discord pin state | `PinTracker` |
| `bot/discord_chat_log.py` | 🟧 Chat audit file | `DiscordChatLog.log_inbound()`, `log_outbound()` |
| `bot/watchdog_service.py` | 🟧 In-process watchdog thread | `WatchdogService.start()`, `stop()`, `pause_bot()` |

### Presentation
| Module | Role | Public surface |
|--------|------|----------------|
| `bot/display.py` | 🟨 Terminal UI | `Display.startup()`, `tick_status()` |
| `bot/report.py` | 🟨 Status/alert formatting | `format_strategy_status()`, `format_trade_executed_alert()` |
| `bot/status.py` | 🟨 Tick summary keys | `build_status_snapshot()` |
| `bot/error_report.py` | 🟨 Error alert formatting | `format_error_alert()`, `error_dedup_key()` |
| `bot/alerts.py` | 🟨 Optional alert channels | `AlertManager`, `AlertConfig` |
| `bot/discord_bot.py` | 🟨 Discord posts + listener + chat maintenance | `DiscordBot.post_important()`, `send_reply()`, `clear_recent_messages()`, `parse_command()` |

## `watchdog/` — monitoring subsystem

| Module | Role | Public surface |
|--------|------|----------------|
| `watchdog/config.py` | 🟧 Watchdog settings | `WatchdogSettings`, `load_settings()` |
| `watchdog/state.py` | 🟧 Persisted dedup + offsets | `WatchdogState.load()`, `record_error()` |
| `watchdog/engine.py` | 🟦 Polling + alerting | `WatchdogEngine.poll_once()`, `request_stop()` |
| `watchdog/parsers.py` | 🟧 Log/receipt parsers | `parse_runtime_errors()`, `parse_receipt()` |
| `watchdog/scoring.py` | 🟩 Health score | `compute_health()`, `HealthReport` |
| `watchdog/alerter.py` | 🟨 Standalone Discord webhook | `DiscordAlerter.post()` |
| `watchdog/main.py` | 🟦 Standalone entry | `python watchdog/main.py` (optional) |

## `tests/`

| File | Covers |
|------|--------|
| `test_portfolio_constraints.py` | feature 001 |
| `test_strategy_governor.py` | feature 002 |
| `test_watchdog_state.py` | feature 006 |
| `test_kraken_retry.py` | feature 008 |
| `conftest.py` | Path setup |

## Dependency direction

Strictly top-to-bottom: presentation → application → domain → infrastructure. No upward imports. The current code mostly respects this; deviations should be flagged in PR review.
