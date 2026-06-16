# Equity DCA (xStocks / ETFs)

Scheduled dollar-cost averaging into Kraken **xStocks** on spot. Runs **in parallel** with crypto strategies (`triangular_arbitrage`, `stat_arb`, `cross_momentum`) — not a replacement.

## Rationale

Offensive strategies use `PROFIT_ONLY_MODE` and `MIN_NET_PROFIT_PCT` because they seek edge. DCA is **scheduled accumulation**: buys are intentional fee drag, not failed arb. The bot therefore:

- Bypasses min-net / edge hurdles for `equity_dca` intents (`is_accumulation`)
- Still enforces `MAX_EQUITY_ALLOCATION_PCT`, drawdown halt, live allowlist, and per-trade USD caps

## Enable (paper)

```env
ENABLE_EQUITIES=1
EQUITY_WATCHLIST=AAPLx,TSLAx,SPYx
DCA_ENABLED=1
DCA_INTERVAL_HOURS=24
DCA_AMOUNT_USD=30
```

- `DCA_AMOUNT_USD` is the **total per cycle**, split evenly across `EQUITY_WATCHLIST` (round-robin — one symbol per interval).
- Or set `DCA_PER_SYMBOL_USD=25` for a fixed USD amount per symbol on independent timers.

`equity_dca` is auto-loaded when `DCA_ENABLED=1` (no need to add it to `STRATEGIES`, though you may).

## Live mirror

Same guardrails as other live trades:

```env
LIVE_ENABLED=1
LIVE_MIRROR_PAPER=1
LIVE_TRADING_CONFIRM=I_ACCEPT_REAL_MONEY
LIVE_ALLOWED_ASSETS=ETH,ADA,AAPLx,TSLAx,SPYx
LIVE_ALLOW_TRIANGULAR=1
LIVE_DRAWDOWN_HALT_PCT=0.10
PROFIT_ONLY_MODE=1
```

DCA buys mirror when the paper trade is CONFIRM and the ticker is in `LIVE_ALLOWED_ASSETS`. Triangular arb is unchanged (`LIVE_ALLOW_TRIANGULAR=1`).

## Scheduling

State persists to `.dca_state.json` (override with `DCA_STATE_FILE`).

| Mode | Behavior |
|------|----------|
| Split budget (default) | Every `DCA_INTERVAL_HOURS`, buy next watchlist symbol with `DCA_AMOUNT_USD / N` |
| Per-symbol | Each symbol buys `DCA_PER_SYMBOL_USD` when its own interval elapses |

## Discord

DCA fills use the **Scheduled equity DCA** headline. In `DISCORD_QUIET_MODE=1`, paper DCA posts only when notional ≥ `DISCORD_PIN_TRADE_USD` (live fills always notify via mirror path).

## Triangular arbitrage

`triangular_arbitrage` scans **crypto only** — equity tickers are excluded from loop permutations even when `ENABLE_EQUITIES=1`.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_equity_dca.py tests/test_triangular_arbitrage.py -q
```

See also [kraken-equities-futures.md](kraken-equities-futures.md).
