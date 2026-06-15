# Live trading on Kraken

Real-money execution is **off by default**. This guide covers arming live mode with your Kraken **ETH** and **ADA** holdings.

## Prerequisites

1. Kraken API key with **Query** + **Trade** permissions only — **never** enable Withdraw.
2. `.env` in the repo root (never commit this file).
3. Conservative trade cap: start with `LIVE_MAX_TRADE_USD=25` or `50`.

## Arm live trading

Add or set these in `.env`:

```env
KRAKEN_API_KEY=your_key
KRAKEN_API_SECRET=your_secret

# Primary switch (LIVE_TRADING_ENABLED is an alias)
LIVE_ENABLED=1
LIVE_TRADING_CONFIRM=I_ACCEPT_REAL_MONEY

# Restrict live to your holdings (default: single-hop */USD only)
LIVE_ALLOWED_ASSETS=ETH,ADA
LIVE_MAX_TRADE_USD=50
LIVE_MAX_USD_PER_TRADE=50

# Optional: sequential multi-hop (ETH/ADA/USD + BTC bridge only)
# LIVE_ALLOW_TRIANGULAR=1
# LIVE_MAX_ROUTE_LEGS=3
# LIVE_MAX_ROUTE_USD=50

# Recommended: paper shadow + live mirror
LIVE_MIRROR_PAPER=1
LIVE_MIRROR_MIN_CONFIDENCE=confirm
# LIVE_MIRROR_UNCERTAIN=0
LIVE_MIN_ETH_RESERVE=0.5
LIVE_DRAWDOWN_HALT_PCT=0.10
LIVE_MAX_TRADES=3
```

Restart TradeBot after editing `.env`:

```powershell
.\scripts\start_tradebot.ps1
```

## What happens when armed

- **Balance sync** — on each live tick, `LiveBroker` calls `fetch_balance()` and syncs ETH, ADA, USD, and BTC as the source of truth (`.live_state.json`).
- **Paper mirror mode** (`LIVE_MIRROR_PAPER=1`) — paper runs in `.paper_state.json`; when a paper trade gets a **CONFIRM** live-viability tag (Kraken fees + ticker), it mirrors to Kraken. Skips are logged to `logs/live_mirror_skips.log` (quiet — no Discord spam).
- **Confidence gating** — `LIVE_MIRROR_MIN_CONFIDENCE` controls mirroring:
  - `confirm` (default) — mirror only when live_tag is CONFIRM (est. net positive after fees)
  - `uncertain_ok` — also allow UNCERTAIN when `LIVE_MIRROR_UNCERTAIN=1`
  - `always` — mirror UNCERTAIN trades too (multi-hop still needs `LIVE_ALLOW_TRIANGULAR`)
  - DENY verdicts never mirror
- When CONFIRM, preflight / `LIVE_STRICT_PROFIT` net-profit blocks are bypassed for the mirror path (safety caps still apply: USD limit, ETH floor, drawdown halt).
- **Restrictions (default)**:
  - Single-hop **ETH/USD** and **ADA/USD** market orders
  - Multi-hop blocked unless `LIVE_ALLOW_TRIANGULAR=1`
- **Triangular live** (`LIVE_ALLOW_TRIANGULAR=1`):
  - Legs execute **sequentially** on Kraken (not atomic like paper)
  - Allowed assets: ETH, ADA, USD (+ BTC as bridge only)
  - Caps: `LIVE_MAX_ROUTE_LEGS`, `LIVE_MAX_TRADE_USD` per leg, `LIVE_MAX_ROUTE_USD` route total
  - Mid-route failure: rollback completed legs; halt + Discord alert if unwind fails
- **Shared safety**:
  - Hard cap per trade (`LIVE_MAX_TRADE_USD`)
  - ETH floor (`LIVE_MIN_ETH_RESERVE`) — live halts if ETH drops below reserve
  - Drawdown halt (`LIVE_DRAWDOWN_HALT_PCT`) — circuit breaker stops live trading
- **Startup warnings** — CRITICAL log line + one-time Discord **LIVE TRADING ARMED** pin when Discord is enabled.
- **Verifier** — real Kraken fills show `✓ Live fill confirmed on Kraken (...)` in Discord trade footers.

## Verify balances (no trades)

```powershell
.\.venv\Scripts\python.exe scripts\anchor_live_session.py
```

Prints ETH, ADA, USD balances and portfolio USD without placing orders.

## Dry-run single sell (optional)

```powershell
.\.venv\Scripts\python.exe scripts\test_live_trade.py
```

Uses the same gates as the bot; only runs when live is armed and keys are set.

## Disarm

```env
LIVE_ENABLED=0
# or remove LIVE_TRADING_CONFIRM
```

Restart the bot. Paper simulation continues with no Kraken orders.

## Safety checklist

| Check | Setting |
|-------|---------|
| Confirm phrase set | `LIVE_TRADING_CONFIRM=I_ACCEPT_REAL_MONEY` |
| Trade cap | `LIVE_MAX_TRADE_USD` ≤ 50 to start |
| Allowed pairs | `LIVE_ALLOWED_ASSETS=ETH,ADA` |
| Triangular live | default OFF; set `LIVE_ALLOW_TRIANGULAR=1` to enable sequential multi-hop |
| Mirror confidence | `LIVE_MIRROR_MIN_CONFIDENCE=confirm` (default) |
| Uncertain mirrors | `LIVE_MIRROR_UNCERTAIN=0` (default OFF) |
| API withdraw disabled | Kraken key permissions |
| Secrets not in git | `.env` is local only |

## Related docs

- [path-to-live-trading.md](path-to-live-trading.md) — phased rollout checklist
- [kraken-prop.md](kraken-prop.md) — Trade Prop eval accounts (not supported; spot only)
- [feature_logs/051_live-kraken-trading.md](../feature_logs/051_live-kraken-trading.md) — implementation log
