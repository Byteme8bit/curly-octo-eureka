# Path to live trading

A phased checklist for building confidence before risking real money. This is **operational guidance**, not financial advice. The bot today uses **`PaperBroker` only** — there is no `LiveBroker`, and WatchDog `-verify` is designed to say so bluntly.

## What your last `-verify 20` actually means

Typical result (paper session with triangular arb enabled):

| Metric | Meaning |
|--------|---------|
| **CONFIRM 0** | No trade passed *all* checks. One DENY on any check marks the whole trade DENY. |
| **DENY 13** | Mostly triangular loops where fee/price checks failed or stacked with multi-hop flags. |
| **UNCERTAIN 7** | Single-leg trades with missing OHLCV history or log correlation gaps — soft issues, not “fake trades.” |
| **Paper PnL $1,845** | Sum of `gain_loss` on reviewed trades — **not** audited as live-realizable while arb dominates. |
| **LIVE_READY: NO** | Expected today: no live broker, >50% multi-hop routes, high trade-level DENY rate. |

### Per-check breakdown (last 20 trades, June 2026 session)

| Check | CONFIRM | DENY | UNCERTAIN | Notes |
|-------|---------|------|-----------|-------|
| existence_correlation | 16 | 0 | 4 | Receipts exist; 4 recent trades missing log window match |
| market_reality | 20 | 0 | 0 | All pairs/assets exist on Kraken |
| price_plausibility | 4 | 0 | 16 | Kraken OHLCV unavailable for trades older than ~few days |
| fee_realism | 20* | 0 | 0 | *After r047 fix: per-leg fee sum with USD prices; before fix, 13 false DENYs on triangular |
| size_constraints | 20 | 0 | 0 | Reserve and min-USD rules replay cleanly |
| multi_hop_atomic | 7 | 0 | 13 | 13 triangular / multi-leg loops — paper assumes atomic execution |
| preflight | 20 | 0 | 0 | Would pass pre-flight on live Kraken fee schedule |
| liquidity | 20 | 0 | 0 | Trade size small vs 24h volume |

**Takeaway:** The verifier is **not** saying “your bot is broken.” It is saying “this paper session is dominated by strategies and infrastructure that are **not live-ready yet**.”

---

## Honest answer: can you go live today?

**No.** Three blockers:

1. **No live execution path** — `TradingEngine` wires `PaperBroker` only; instant fills, no order IDs, no exchange reconciliation.
2. **Triangular arb dominates** — 65% of recent trades are 3–4 leg loops. Paper executes them atomically; Kraken does not.
3. **Paper PnL is not independently confirmed** — fee and price checks on loops were skewed (now improved); OHLCV history gaps leave many fills UNCERTAIN, not CONFIRM.

Positive signals: receipts correlate, markets are real, pre-flight would allow the trades, constraints replay correctly.

---

## Phased roadmap

### Phase 0 — Paper integrity (days–weeks)

**Goal:** Make paper sessions trustworthy enough that `-verify` reflects reality, not verifier bugs.

| Step | Bot work | You verify |
|------|----------|------------|
| Align fee model | Ensure `PaperBroker` uses same `FeeEngine` as pre-flight (already true when `FEE_FORCE_STATIC=0`). Set `FEE_RATE` to your expected Kraken tier or enable auth for personalized fees. | Compare one receipt’s `fee_usd` to Kraken fee schedule manually. |
| Fix verifier fee on multi-hop | Sum per-leg notionals × taker fee (done in r047). | Re-run `-verify 20`; DENY count on triangular should drop if fees match. |
| OHLCV / price tolerance | For recent trades (<48h), OHLCV should work. Older trades → UNCERTAIN is correct. Optionally widen `VERIFIER_PRICE_TOLERANCE_PCT` only after seeing false DENYs on *recent* single-leg fills. | Run `verify_trades.py --last 5` on trades from today. |
| Triangular on paper | **Option A:** `STRATEGIES=cross_momentum,stat_arb` (drop triangular) for cleaner verify scores. **Option B:** keep triangular but accept UNCERTAIN on `multi_hop_atomic` until Phase 4. | Decide whether paper PnL should include arb you cannot live-execute. |
| Weekly verify cadence | None — use existing CLI / Discord. | `WatchDog -verify 20` weekly; archive JSON from `reports/`. |

**Exit criteria:** Single-leg paper trades (ETH/USD, USD→alt) reach mostly CONFIRM; triangular either disabled or understood as UNCERTAIN-only.

---

### Phase 1 — Shadow mode (1–2 weeks)

**Goal:** Log **intended** live orders without sending them.

| Step | Bot work | You verify |
|------|----------|------------|
| Add `SHADOW_MODE=1` | After pre-flight pass, write shadow order JSON (pair, side, qty, limit/market, expected fee) to `shadow_orders/` instead of `PaperBroker.execute`. | Diff shadow orders vs what paper would have done for 1 week. |
| Shadow PnL estimate | Mark-to-market shadow fills using Kraken tickers at decision time. | Compare shadow vs paper on single-leg trades only. |

**Exit criteria:** Shadow log matches paper decisions on simple routes; no silent drops.

---

### Phase 2 — LiveBroker minimal (weeks)

**Goal:** Real money on **one leg only** — e.g. ETH/USD or USD→ETH — with read-only safety rails.

| Step | Bot work | You verify |
|------|----------|------------|
| Implement `bot/live_broker.py` | ccxt authenticated Kraken: `create_order`, `fetch_balance`, `fetch_my_trades`. Hard-cap: `LIVE_MAX_USD_PER_TRADE`, `LIVE_ALLOWED_PAIRS=ETH/USD`. | Kraken API keys with **trade** permission only on a sub-account or minimal balance. |
| Kill switch | `LIVE_ENABLED=0` default; engine refuses live if unset. | Confirm bot starts with live disabled. |
| Reconciliation | After each fill, compare exchange balance to internal state; halt on drift. | Manual spot-check first 10 live fills on Kraken UI. |
| Disable arb strategies live | `LIVE_STRATEGIES=cross_momentum` or stat_arb single-leg only. | Never enable triangular on first live capital. |

**Exit criteria:** 20+ live single-leg trades reconciled; zero unexplained balance drift.

---

### Phase 3 — Watchdog exchange reconciliation (1 week)

**Goal:** Independent proof that live fills match bot records.

| Step | Bot work | You verify |
|------|----------|------------|
| Extend verifier | New check: `fetch_my_trades` vs receipt / state (order id, qty, price, fee). | Run verifier after each live session. |
| Discord `-verify` | Include “live reconciliation: N/M matched” when `LIVE_ENABLED=1`. | Weekly audit. |

**Exit criteria:** 100% match on live trades for 2 consecutive weeks.

---

### Phase 4 — Multi-hop / triangular (months, optional)

**Goal:** Only pursue if edge justifies leg risk and engineering cost.

| Step | Bot work | You verify |
|------|----------|------------|
| Sequential legs with rollback | Execute leg 1, confirm fill, then leg 2; abort / unwind if edge gone. | Paper-simulate stall on leg 2. |
| Or disable live triangular | Keep triangular paper-only for research. | Accept that live PnL ≠ paper PnL. |

**Exit criteria:** Documented max loss on stalled loop; verifier `multi_hop_atomic` CONFIRM only with rollback tests.

---

### Phase 5 — Verifier green threshold (ongoing)

**Goal:** Define “ready to increase size” using `-verify`, not gut feel.

Suggested gates (single-leg sessions, triangular disabled or excluded):

| Gate | Threshold |
|------|-----------|
| Trade-level CONFIRM rate | ≥ **80%** on last **N=30** trades |
| Trade-level DENY rate | ≤ **5%** |
| Receipt/log integrity DENY | **0%** |
| LIVE_READY banner | **YES — paper session verified** (still not “go live” until Phase 2+) |
| Live money | Requires Phase 2 + 3 complete; banner still notes live broker exists |

Commands:

```powershell
.\.venv\Scripts\python.exe scripts\verify_trades.py --last 30 --summary-only
.\.venv\Scripts\python.exe scripts\verify_trades.py --last 30 --json
```

---

## When `-verify` shows what

| Banner | Paper-only bot | After LiveBroker exists |
|--------|----------------|-------------------------|
| **NO — DO NOT TRADE** | Missing integrity, high DENY, triangular majority, or fee/price unrealistic | Same + live reconciliation failures |
| **CONDITIONAL** | Some trades OK; mixed UNCERTAIN (logs, OHLCV, multi-hop) | Paper OK but live not yet reconciled |
| **YES — paper session verified** | Simple routes mostly CONFIRM; **still no real money** | Means paper audit passed — **not** permission to size up live until Phase 3 green |

The WHY line **“No live broker in codebase”** appears until `bot/live_broker.py` exists and is importable.

---

## Bot vs you — quick reference

| Concern | Bot must change | You must verify |
|---------|-----------------|-----------------|
| Real fills | LiveBroker, shadow mode | Kraken UI, API trade history |
| Fees | FeeEngine + PaperBroker alignment | Fee tier, receipts |
| Triangular PnL | Disable live or sequential legs | Whether paper arb PnL is actionable |
| Verify scores | Verifier fairness, leg fee sums | Weekly `-verify`, archive reports |
| Capital safety | Kill switch, pair caps, reconciliation | Sub-account sizing, manual review |

---

## Optional: cleaner verify scores now

If triangular paper profits distort confidence:

```env
STRATEGIES=cross_momentum,stat_arb
```

Reset paper state only if you accept losing history (`RESET_PAPER_STATE=1` once). Re-run `-verify 20` after a week of simple-route trading.

---

## Related docs

- [Independent verification](independent-verification.md) — check definitions and env knobs
- [Architecture overview](architecture/overview.md) — tick lifecycle and strategy plugins
