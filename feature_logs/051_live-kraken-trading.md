# 051 — Live Kraken trading

**Requested:** 2026-06-13
**Status:** awaiting verification — pytest pending (watchdog dedup tests pass locally)

## Request
Go live with real Kraken money: cross-pair + arbitrage strategies, profitable trades only,
hard halt at 10% portfolio drawdown from peak.

## Actions taken
- Added `bot/live_broker.py` — ccxt market orders, multi-leg paths, balance sync, halt flag
- Added `bot/live_guards.py` — `LIVE_TRADING_CONFIRM` arm gate, `LIVE_ALLOWED_ASSETS`, multi-hop block
- `LIVE_ENABLED=1` (or `LIVE_TRADING_ENABLED=1`) wires `LiveBroker` when confirm phrase set
- **`LIVE_TRADING_CONFIRM=I_ACCEPT_REAL_MONEY`** required to start with live enabled
- **`LIVE_ALLOWED_ASSETS=ETH,ADA`** — live v1 single-hop ETH/USD and ADA/USD only; no triangular live
- **`LIVE_MIRROR_PAPER=1`** — paper runs continuously (`.paper_state.json`); when a paper trade clears all gates, the same route mirrors to Kraken if live gates pass (`.live_state.json`). Paper keeps adaptive/probes; live halts (drawdown, ETH floor, max trades) stop mirror only.
- Live config: `LIVE_MAX_TRADE_USD` / `LIVE_MAX_USD_PER_TRADE`, `LIVE_DRAWDOWN_HALT_PCT=0.10`, `LIVE_STRICT_PROFIT`
- **`LIVE_MIN_ETH_RESERVE=0.5`** — hard ETH floor; halts live trading if balance drops below 0.5 ETH
- Each live tick syncs Kraken balances then checks ETH floor; sub-floor triggers `broker.halt` + `set_trading_active(False)` + Discord alert
- Trade intents blocked if they would sell ETH below 0.5 (open sells, triangular legs, cross-pair routes); alt→ETH de-risk trims still allowed
- 10% drawdown forces circuit breaker + stops runtime trading + sets broker halt on live
- Live mode disables adaptive threshold relaxation and idle probes
- **Dashboard live mode** — when `LIVE_ENABLED=1`, reads `.live_state.json` balances/risk (not paper snapshot); shows LIVE badge; trade count from `live_trades_completed`
- **Split dashboards** — `/paper` (or `/`) for paper-only metrics; `/live` for Kraken live metrics; mode-specific API routes (`/api/paper/*`, `/api/live/*`, `?mode=paper|live`); nav toggle; live halt/ETH floor/max trades strip; mirror note on live page
- Tests: `tests/test_live_broker.py`, `tests/test_live_eth_floor.py`, `tests/test_live_guards.py`, `tests/test_dashboard_live.py`, paper/live split in `tests/test_dashboard.py`
- Docs: `docs/live-trading.md` — arm steps, safety checklist
- **Goal 1 ($10k portfolio)** — primary milestone: live portfolio tracking in mirror mode, dashboard progress bar, Discord startup/heartbeat, `.tradebot_goals_state.json` reset to live baseline (~$1654)

## Goal 1 — $10,000 portfolio (Growth tier)
- First primary goal = `$10,000` portfolio (`GOAL_MILESTONES_USD` first entry)
- **Unlocks at $10k:** Growth tier — adds `stat_arb` (Stat-arb pairs)
- Mirror mode tracks **live** Kraken portfolio for goals; dashboard shows live + paper reference
- Set `GOAL_EVOLUTION_ENABLED=1` in `.env` (user env currently `0` — enable for goals UI/Discord)

## ADA-first funding (session start)
- `CORE_ASSETS=ADA,ETH,BTC,...` and `PREFERRED_START_ASSETS=ADA` — spend ADA before ETH above `LIVE_MIN_ETH_RESERVE`
- `bot/funding_priority.py` ranks funding sources; ETH always last among held assets
- Cross-momentum rotation, orchestrator tie-breaks, and idle probes all prefer ADA → USD → ETH
- With ~$14 ADA + $18 USD: USD funds expansion buys; ADA funds rotations (~$10 min at bumped size); ETH stays at 0.964 (floor 0.5 untouched)
- Tests: `tests/test_funding_priority.py`

## User .env (do not commit)
```env
CORE_ASSETS=ADA,ETH,BTC,LTC,XRP
PREFERRED_START_ASSETS=ADA
LIVE_ENABLED=1
LIVE_TRADING_CONFIRM=I_ACCEPT_REAL_MONEY
LIVE_ALLOWED_ASSETS=ETH,ADA
LIVE_MIRROR_PAPER=1
LIVE_MAX_TRADE_USD=50
LIVE_MAX_USD_PER_TRADE=50
LIVE_DRAWDOWN_HALT_PCT=0.10
LIVE_STRICT_PROFIT=1
LIVE_MIN_ETH_RESERVE=0.5
LIVE_MAX_TRADES=3
STRATEGIES=cross_momentum,triangular_arbitrage,stat_arb
CIRCUIT_BREAKER_ENABLED=1
```

## Discord quiet mode (2026-06-13)
Reduce chat noise while keeping LIVE trades, halts, circuit breaker, errors.

**User `.env` (not committed):**
```env
DISCORD_QUIET_MODE=1
WATCHDOG_QUIET_MODE=1
DISCORD_HEARTBEAT_MINUTES=120
DISCORD_TRADE_SUMMARY_INTERVAL_MINUTES=0
DISCORD_MAJOR_MOVE_PCT=0
AUDITOR_DISCORD_QUIET=1
WHALE_WATCH_DISCORD_ALERTS=0
DISCORD_WHALE_SKIP_TO_DISCORD=0
```

**Code:** mirror mode skips paper trade Discord (live mirror posts only); quiet mode suppresses paper trades, PnL milestones, major moves, goal tier-ups, whale-follow, probe, heartbeat goal lines.

Restart bot after deploy.

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_goal_evolution.py tests\test_dashboard.py::test_build_goals_view tests\test_dashboard.py::test_build_goals_view_primary_goal -q
.\.venv\Scripts\python.exe -m pytest tests\test_live_broker.py tests\test_live_eth_floor.py tests\test_live_guards.py tests\test_live_mirror.py tests\test_live_verify_tag.py tests\test_verifier.py -q
.\.venv\Scripts\python.exe main.py
```

## Notes
- Triangular arb executes legs sequentially on Kraken when `LIVE_ALLOW_TRIANGULAR=1`; a failed mid-path leg attempts rollback, then halts + Discord alert if unwind fails.
- Route caps: `LIVE_MAX_ROUTE_LEGS` (default 3), `LIVE_MAX_TRADE_USD` per leg, `LIVE_MAX_ROUTE_USD` route total.
- Live routes restricted to ETH, ADA, USD (+ BTC bridge); UNI/AAVE-style loops remain paper-only.
- User portfolio is ~0.975 ETH / $0 USD — expect cross-pair and sell-side routes first.
- Revoke and rotate API keys if ever pasted in chat.
