# 030 — Retune for net-positive (not "trade at any cost")

**Requested:** 2026-06-01 07:25 PDT
**Status:** complete — awaiting verification (pytest green in worktree: 305 passed)

## Request
Shift the bot from "trade at any cost" to **net-positive** trading after real
fees + slippage, while keeping reasonable activity, diversification and
loss-mitigation. Specifically: turn off `FEE_FORCE_STATIC` (use real fees),
raise `MIN_TRADE_EDGE` above true breakeven, disable / break-even-gate the
forced probe, and **investigate + fix the triangular-arbitrage loop** (suspected
leg-1-only churn). Run isolated paper sessions and compare a selective/profit
config vs the current activity config with real numbers.

## Root causes of the fee bleed
1. **Triangular arb fired only leg 1 of the loop (the big bug).**
   `TriangularArbitrageStrategy` simulated a full A→B→C→A loop but emitted a
   `TradeIntent(from=A, to=B)` — only the *first* leg. The engine executed just
   A→B, paid a fee, and **stranded the intermediate coin** (e.g. ETH→UNI with no
   UNI→AAVE→ETH). Legs 2/3 never ran, so the "loop profit" never materialised:
   pure directionless fee churn. It also handed pre-flight a fee-inclusive number
   as `gross_return_pct` while pre-flight only charged one leg's fee.
2. **`FEE_FORCE_STATIC=1` + `FEE_RATE=0.0026`** made the gate assume 0.26% fees.
   Kraken's real public taker is **0.40%** (confirmed via `load_markets`). A
   ~0.40% gross trade cleared the optimistic gate but loses on real fees.
3. **`MIN_TRADE_EDGE=0.0015`** sat below real round-trip breakeven.
4. **`IDLE_PROBE_FORCE_MINUTES=15`** forced a fee-losing probe purely "to stay
   active" — `_maybe_force_probe` bypassed the edge/fee gates by design.
5. **Bonus finding — defensive "mitigating losses" exit churn.** The momentum
   exit trims `TRADE_SIZE_PCT` of a holding to USD whenever its score dips below
   `MOMENTUM_SELL` (default **−0.002**, i.e. −0.2% noise), and is `is_defensive`
   so it **bypasses pre-flight**. In a mildly negative window it re-trims the
   same coin every cooldown, paying a fee each time. This was the largest live
   bleed observed (see evidence).

## Actions taken (code)
- `bot/strategies/base.py` — `TradeIntent` gains an optional pre-built
  `route` (the whole multi-leg loop). When set, the engine executes that route
  atomically instead of re-deriving a single leg from from/to.
- `bot/strategies/triangular_arbitrage.py` — now emits the **whole closed loop**
  as one atomic intent (`from_asset == to_asset == start`, `route` = all 3 legs)
  with a **pre-fee** `gross_return_pct` so pre-flight subtracts real compounded
  fees. A loop either completes in one shot or does not fire — no more leg-1
  stranding. Refuses non-closed loops.
- `bot/engine.py`:
  - `_execute_intent` and the tick validation use `intent.route` when present.
  - `_maybe_force_probe` now **break-even-gates** the probe: it re-runs the
    chosen candidate through pre-flight with live fees and a `min_net_profit=0.0`
    floor; if it can't clear real fees + slippage it is skipped. A zero-edge
    probe can therefore never lose money, making `IDLE_PROBE_FORCE_MINUTES` safe.

## Recommended LIVE `.env` values
```
FEE_FORCE_STATIC=0          # use real (~0.40%) Kraken taker fees
FEE_RATE=0.004              # realistic taker; also the paper-broker fill fee + risk hurdle base
MIN_TRADE_EDGE=0.010        # ~1.0%: clears 2-leg fees (0.8%) + slippage + margin
MIN_NET_PROFIT_PCT=0.002    # pre-flight net floor, comfortably > 0 after real fees
IDLE_PROBE_FORCE_MINUTES=0  # forced probe off (and now break-even-gated even if >0)
MOMENTUM_SELL=-0.006        # only exit on a real -0.6% break, not -0.2% noise
TRADE_COOLDOWN_SECONDS=180  # throttle defensive re-trims (keep production value)
MAX_TRADES_PER_HOUR=12
```
Diversification, alt caps, ETH reserve, circuit breaker and the defensive exit
all remain ON — just less trigger-happy.

## Verification — isolated paper runs (worktree `eth-trading-bot-tune2`)
Drift-neutral metric `trading_vs_hold` = end portfolio − value of the *initial*
basket at end prices (isolates trading drag from market drift). ~2-min windows,
live Kraken public data, `RESET_PAPER_STATE=1`, no secrets, Discord/auditor off.

| Config (window) | Trades | Probe | trading_vs_hold |
|---|---|---|---|
| activity (current code) | 1 | 1 (forced probe ETH→BTC) | **−$0.55** |
| activity (fixed code, down window, 5s test cooldown) | 9 defensive trims | 0 | **−$8.63** |
| **selective (fixed code, MOMENTUM_SELL=-0.006, 60s cooldown)** | **0** | 0 | **$0.00** |

Short windows can't reproduce 24h PnL and market drift dominates raw PnL, so the
reproducible wins are captured as unit tests (`pytest -q` → **305 passed**):
- `tests/test_triangular_arbitrage.py` — loop emits a closed atomic route,
  executes in one shot ending on the start asset (intermediates = 0), and a
  flat (no-edge) loop does not fire.
- `tests/test_fee_gate.py` — a 0.40% trade clears the optimistic 0.26% gate but
  is rejected under real 0.40% fees; a zero-edge probe is blocked at break-even
  while a genuinely +net probe is allowed.

The selective run held exactly with the market (0 churn) — i.e. it **stops the
bleed**: losses become pure market exposure, not fees. Net-positive over any
given short window is NOT guaranteed by markets and was not claimed.

## Notes
- Partly reverses the "activity" intent of logs 025/026/028 (idle probe,
  force-active trading): those optimised for visible action; this re-prioritises
  not losing money. The probe is kept but can now only fire non-losing trades.
- The triangular fix makes genuine loops very rare (a real >~1.3% net 3-leg arb
  on Kraken spot is essentially nonexistent) — which is the honest outcome: no
  free lunch, but also no fee churn.
- The defensive-exit churn was throttled in production by the real cooldown; the
  9-trim run used a 5s test cooldown. The `MOMENTUM_SELL` raise is the real fix.
