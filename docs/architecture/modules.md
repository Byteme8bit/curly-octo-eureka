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
| `bot/engine.py` | 🟦 Tick orchestration, live mirror, Discord commands | `TradingEngine.run()`, `tick()`, `shutdown()`, `_handle_discord_command()` |
| `bot/runtime.py` | 🟦 Lifecycle flags | `BotRuntime.is_trading_active()`, `request_shutdown()` |

### Domain — strategies
| Module | Role | Public surface |
|--------|------|----------------|
| `bot/orchestrator.py` | 🟩 Merge + rank strategy outputs | `StrategyOrchestrator.evaluate()` |
| `bot/strategies/base.py` | 🟩 Strategy interface | `Strategy`, `TradeIntent`, `StrategyResult` |
| `bot/strategies/cross_momentum.py` | 🟩 Strategy plugin | `CrossMomentumStrategy` |
| `bot/strategies/stat_arb.py` | 🟩 Strategy plugin | `StatArbStrategy` |
| `bot/strategies/triangular_arbitrage.py` | 🟩 Strategy plugin | `TriangularArbitrageStrategy` |
| `bot/strategies/equity_dca.py` | 🟩 Scheduled xStock DCA | `EquityDcaStrategy` |
| `bot/strategies/whale_follow.py` | 🟩 Whale signal mirror | `WhaleFollowStrategy` |
| `bot/strategies/momentum_rotation.py` | 🟩 Strategy plugin (legacy) | `MomentumRotationStrategy` |
| `bot/strategies/registry.py` | 🟩 Strategy lookup | `build_orchestrator()`, `STRATEGY_REGISTRY` |
| `bot/risk.py` | 🟩 Trade gates + cooldowns | `RiskManager`, `TradeGate` |
| `bot/portfolio_constraints.py` | 🟩 ETH floor, alt cap, crypto/equity buckets | `PortfolioConstraints.validate_intent()` |
| `bot/strategy_governor.py` | 🟩 Stickiness + experimentation | `StrategyGovernor.apply()`, `record_trade()` |
| `bot/preflight.py` | 🟩 Net-positive pre-flight | `PreFlightValidator.validate()` |
| `bot/circuit_breaker.py` | 🟩 Drawdown halt | `CircuitBreaker.check()` |
| `bot/fee_engine.py` | 🟩 Fee + slippage math | `FeeEngine.compute_net()` |
| `bot/adaptive.py` | 🟩 Idle threshold relaxation | `AdaptiveStatus`, `compute_relax_factor()` |
| `bot/markets.py` | 🟩 Pair discovery + routing | `Markets.find_path()` |
| `bot/equities.py` | 🟩 xStock pair discovery + watchlist | `filter_equity_watchlist()`, `inject_equity_markets()` |
| `bot/trade_context.py` | 🟩 News + flow regime gates | `TradeContextChecker`, `compute_market_flow()` |
| `bot/goal_evolution.py` | 🟩 Tiered growth goals | `GoalEvolutionManager`, `compute_primary_goal()` |
| `bot/funding_priority.py` | 🟩 Bucket rebalance priority | `funding_rank()` |

### Domain — live trading
| Module | Role | Public surface |
|--------|------|----------------|
| `bot/live_broker.py` | 🟩 Real Kraken spot execution | `LiveBroker.execute_path()`, `sync_from_exchange()`, `halt()` |
| `bot/live_portfolio.py` | 🟩 Live USD valuation + drawdown | `load_live_usd_prices()`, `load_live_portfolio_snapshot()` |
| `bot/live_mirror.py` | 🟩 Paper→live mirror gating | `should_mirror_to_live()`, `append_live_mirror_skip()` |
| `bot/live_guards.py` | 🟩 Live route allowlist + arm check | `check_live_route()`, `is_live_armed()` |
| `bot/paper_anchor.py` | 🟩 Paper←live balance sync | `anchor_paper_broker_to_live()`, `live_balances_snapshot()` |

### Infrastructure
| Module | Role | Public surface |
|--------|------|----------------|
| `bot/data.py` | 🟧 Kraken REST + retry | `KrakenData.fetch_ticker()`, `fetch_all_candles()` |
| `bot/paper_broker.py` | 🟧 Simulated execution | `PaperBroker.execute_path()`, `RiskState`, `PaperState` |
| `bot/paper_portfolio.py` | 🟧 Paper snapshot file | `PaperPortfolioLog.write()`, `load()` |
| `bot/trade_log.py` | 🟧 Per-tick log file rotation | `TradeLog.log()` |
| `bot/local_time.py` | 🟧 Pacific time helpers | `format_pacific()`, `PACIFIC` |
| `bot/pin_tracker.py` | 🟧 Discord pin state | `PinTracker` |
| `bot/discord_chat_log.py` | 🟧 Chat audit file | `DiscordChatLog.log_inbound()`, `log_outbound()` |
| `bot/force_trade_log.py` | 🟧 Force-command audit | `append_force_trade_log()` |
| `bot/whale_watch.py` | 🟧 Large-trade polling | `WhaleWatcher`, `detect_large_trades()` |
| `bot/whale_follow_log.py` | 🟧 Whale follow audit | `append_whale_follow_skip()` |
| `bot/singleton.py` | 🟧 PID lock | `acquire_lock()`, `release_lock()` |
| `bot/fatal_error_log.py` | 🟧 Startup crash capture | `log_fatal()` |
| `bot/watchdog_service.py` | 🟧 In-process watchdog thread | `WatchdogService.start()`, `stop()`, `pause_bot()` |
| `bot/auditor_service.py` | 🟧 In-process auditor thread | `AuditorService.start()`, `stop()`, `run_audit()`, `confirm_proposal()`, `note_trade()` |
| `bot/auditor/` | 🟧 Auditor support package | `analyze_trades()`, `forecast_pnl()`, `NewsClient`, `propose_changes()`, `render_markdown_report()`, `render_discord_summary()`, `AuditorState`, `apply_proposal()` |

### Presentation
| Module | Role | Public surface |
|--------|------|----------------|
| `bot/display.py` | 🟨 Terminal UI | `Display.startup()`, `tick_status()` |
| `bot/report.py` | 🟨 Status/alert formatting | `format_strategy_status()`, `format_trade_executed_alert()` |
| `bot/discord_summary.py` | 🟨 Tick activity line | `format_tick_activity_line()` |
| `bot/status.py` | 🟨 Tick summary keys | `build_status_snapshot()` |
| `bot/error_report.py` | 🟨 Error alert formatting | `format_error_alert()`, `error_dedup_key()` |
| `bot/alerts.py` | 🟨 Optional alert channels | `AlertManager`, `AlertConfig` |
| `bot/discord_bot.py` | 🟨 Discord posts + listener + chat maintenance | `DiscordBot.post_important()`, `send_reply()`, `clear_recent_messages()`, `parse_command()` |

## `bot/verifier/` — independent trade audit

| Module | Role | Public surface |
|--------|------|----------------|
| `bot/verifier/core.py` | 🟦 Verification orchestration | `verify_trades()` |
| `bot/verifier/checks.py` | 🟩 Per-trade checks | fee, constraint, correlation checks |
| `bot/verifier/kraken.py` | 🟧 Public Kraken price fetch | Kraken price helpers for verification |
| `bot/verifier/live_tag.py` | 🟩 CONFIRM/UNCERTAIN/DENY tags | `build_live_verify_tag()`, `is_multi_hop_trade()` |
| `bot/verifier/parsers.py` | 🟧 Receipt/log parsers | `parse_receipt()`, `parse_session_log()` |
| `bot/verifier/report.py` | 🟨 HTML/JSON report render | `render_html()`, `render_json()` |
| `bot/verifier/__main__.py` | 🟦 CLI entry | `python -m bot.verifier` |

See [`../independent-verification.md`](../independent-verification.md).

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

## `dashboard/` — local read-only UI

| Module | Role | Public surface |
|--------|------|----------------|
| `dashboard/app.py` | 🟦 FastAPI routes | `create_app()` — `/paper`, `/live`, `/api/*` |
| `dashboard/__main__.py` | 🟦 HTTP server entry | `python -m dashboard` |
| `dashboard/service.py` | 🟦 Overview data assembly | `build_overview()` |
| `dashboard/parsers/live_portfolio.py` | 🟧 Live valuation for UI | `load_live_portfolio()` — uses `bot.live_portfolio.load_live_usd_prices()` |
| `dashboard/parsers/tradebot.py` | 🟧 Paper portfolio parser | holdings, PnL series |
| `dashboard/parsers/auditor.py` | 🟧 Auditor report parser | latest audit markdown |
| `dashboard/parsers/watchdog.py` | 🟧 Watchdog health parser | health score, errors |
| `dashboard/parsers/whales.py` | 🟧 Whale activity parser | recent whale events |

Default URL: `http://127.0.0.1:8765`. See feature log 034/035.

## `tests/`

| File | Covers |
|------|--------|
| `test_portfolio_constraints.py` | ETH floor, alt cap, crypto/equity buckets |
| `test_strategy_governor.py` | stickiness / exploration |
| `test_watchdog_state.py` | dedup + offsets |
| `test_kraken_retry.py` | Kraken REST retry |
| `test_auditor.py` | auditor bot |
| `test_live_mirror.py` | paper→live mirror gating |
| `test_dashboard_live.py` | live valuation (paper/live price merge) |
| `test_equity_dca.py` | equity DCA scheduling |
| `test_force_command.py` | Discord `-force` command |
| `test_resume_live_halt.py` | `-resume-live` halt clear |
| `conftest.py` | Path setup |

## Dependency direction

Strictly top-to-bottom: presentation → application → domain → infrastructure. No upward imports. The current code mostly respects this; deviations should be flagged in PR review.
