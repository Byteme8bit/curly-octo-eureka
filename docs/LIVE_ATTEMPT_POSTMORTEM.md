# Live Attempt Postmortem (2026-06-14 — 2026-06-19)

> **Purpose:** Explain why the first live-mirror attempt was harder than expected, what actually traded, whether it made money, and how to do better next time.
>
> **Reset date:** 2026-06-24 — paper-only mode restored; baseline anchored to Kraken (~$1,589).

---

## Executive summary

The bot went live on **2026-06-14** with a ~**$1,650–1,724** Kraken portfolio and ran **live mirror mode** for five days. **22 live trades** executed (~$10.38 in fees). The wallet ended around **$1,587–1,589** — a modest **~$65–135 loss** from the opening range, not the catastrophic **84% drawdown** the dashboard once displayed.

The live attempt failed operationally more than financially: **paper/live divergence**, **fee floors blocking offense**, **config churn**, **mirror guard bugs**, a **valuation false halt**, and **complexity creep** (triangular arb, xStocks, futures, 50/50 buckets) made it hard to know what was real vs simulated.

---

## 1. Paper vs live divergence (phantom PnL)

### What happened

| Layer | Portfolio ~Jun 16 | Problem |
|-------|-------------------|---------|
| **Paper** | $8k–12k+ (inflated) | Ran triangular arb, DOT/UNI multi-hop, bucket trims freely |
| **Live Kraken** | ~$1,650–1,685 | Only mirrored subset; many paper routes never executed |
| **Dashboard** | Showed 84% drawdown once | Priced live ETH at **$0** because paper had sold all ETH |

### Root causes

1. **Separate books** — Paper and live state files diverged immediately after mirror mode started. Paper kept trading assets live was not allowed to hold (DOT, UNI, AAVE).
2. **Paper anchor lag** — `PAPER_ANCHOR_TO_LIVE=1` helped on startup but paper re-inflated within hours as strategies ran unrestricted.
3. **`PAPER_MIRROR_LIVE_ONLY=1`** — Paper could only trade routes live could mirror, but live guards still blocked many of those; paper idle logic and probes created confusion about "why no live fill."
4. **Valuation bug (feature 072 / PR #65)** — `_usd_prices()` preferred paper holdings; when paper sold ETH into alts, live ETH was priced at $0 → false **LIVE HALT** while Kraken balance was intact.

### Evidence

- `.live_state.json`: 22 `live: true` trades; balances ETH 0.71, USD 416, ADA 24.5
- `.paper_state.json` (pre-reset): same balances after anchor but **1,500+ paper trades** in history
- `feature_logs/072_live-valuation-false-halt.md`: documented false 84% drawdown
- `docs/PROJECT_HANDOFF.md` §6: "Do not trust paper PnL for live decisions"

### Lesson

**Treat paper PnL as strategy signal only after anchor — never as live PnL.** Before any live session, anchor paper to Kraken and disable strategies that live cannot execute.

---

## 2. Fee floor / taker fees blocking offensive trades

### What happened

`PROFIT_ONLY_MODE=1` + realistic Kraken fees (`FEE_FORCE_STATIC=0`) + `MIN_TRADE_EDGE` / `FEE_SAFETY_MULTIPLIER` meant most offensive rotations **failed preflight** with net ≤ 0.

`logs/trade_diagnosis.json` (2026-06-19) shows:

- Best route `USD→ADA`: edge +0.00114, **required +0.00216** — blocked
- Typical blocked reason: `Pre-flight reject: net -0.0034 (gross +0.0011 - fees 0.0040 - slippage 0.0005)`
- Bot idle **56+ hours** with adaptive relax at 0.5× — still no qualifying offensive trade

### What did execute live

| Category | Count | Notes |
|----------|-------|-------|
| Defensive momentum sells | ~10 | ADA/ETH/BTC → USD on negative momentum; **negative edge** on many |
| Portfolio cap / bucket trims | 4 | ADA concentration, crypto bucket >55% |
| Forced probes | 1 | ETH→BTC probe; lost ~$0.56 |
| Triangular arb (4-leg) | 6 | **Largest losses** — est net positive in reason string, actual **-$2 to -$11** per loop |
| Manual connectivity test | 1 | ETH→USD sell $17.93 |

Defensive and probe trades **cleared the mirror** because they were categorized as risk reduction or had attached edge metadata — but many still had **negative net after fees**.

### Lesson

- **Offense was blocked; defense and arb slipped through** — asymmetric gate behavior.
- For next live attempt: **single-hop only**, higher `MIN_NET_PROFIT_PCT`, and **block all negative-edge mirrors** including defensive trims until fee model is proven.
- Run paper-only for 1–2 weeks with **same fee engine** and measure net edge distribution before arming live.

---

## 3. Config churn, restarts, and PID confusion

### What happened

`logs/autostart.log` and dozens of `bot_stdout_*.log` / `bot_stderr_*.log` files show **frequent restarts** during Jun 14–19:

- `.env` changed repeatedly: `LIVE_MAX_ROUTE_LEGS` (1→3→4→1), `LIVE_ALLOWED_ASSETS`, `MIN_TRADE_EDGE`, `LIVE_DRAWDOWN_HALT_PCT` (0.10→0.18), equity/futures flags
- Multiple concurrent `python main.py` processes (non-venv vs venv) before singleton hardening
- `runtime_overrides.json` (auditor) bumped `TRADE_SIZE_PCT` to 0.2 — removed in feature 074 restart
- User stopped all processes manually on 2026-06-16 crisis

### Lesson

- **Freeze config** for 48h minimum per live stage; one change per restart.
- Keep a **config journal** (feature log or `runtime_overrides` audit) — not ad-hoc `.env` edits mid-session.
- Always use `scripts/start_tradebot.ps1` + `scripts/is_tradebot_running.py`; never raw `python main.py` from system Python.

---

## 4. Mirror bugs (edge, triangular, allowed assets)

### 4a. Edge attached after live tag (feature 075)

Paper offensive trades showed positive momentum edge in logs, but live mirror saw **gross 0.0** → **DENY** from verifier. Fixed by attaching `edge` before `_mirror_intent_to_live`. Still blocked afterward by negative-net guard — fix was necessary but not sufficient.

### 4b. Triangular / multi-hop

`logs/live_mirror_skips.log` (400 lines) dominated by:

- `Route has 4 legs — LIVE_MAX_ROUTE_LEGS=3` (later 1)
- `Live route asset DOT not allowed`
- `Paper-only / multi-hop — live execution uncertain`

When 4-leg mirror **was** enabled (Jun 16), six triangular loops executed live with **~$1.20–1.22 fees each** and **reported gain_loss -$2 to -$11** per loop — paper estimated "est net +0.01–0.06" but reality was slippage across four taker legs.

### 4c. Allowed assets mismatch

`LIVE_ALLOWED_ASSETS=ETH,ADA,BTC,USD` blocked UNI/DOT/ATOM routes paper kept finding. Expanding allowed assets (075) opened more loss vectors without proving single-hop edge first.

### Lesson

- **Never enable live triangular** until paper proves positive net over 100+ loops at live fee tier.
- Keep `LIVE_MAX_ROUTE_LEGS=1` for first live month.
- Allowed assets list should match **exactly** what you hold and want to trade — no "just in case" alts.

---

## 5. False halts / circuit breaker / valuation bugs

| Event | Date | Impact |
|-------|------|--------|
| Valuation false halt | 2026-06-16 ~10:30 PDT | LIVE HALT; Kraken intact ~$1,685 |
| UNI/BTC insufficient funds | 2026-06-16 | Multi-hop route halt mid-loop |
| Drawdown halt threshold | 18% configured | Session re-anchored to $1,203 on Jun 19 lowered perceived loss |

The **worst moment was operational panic**, not actual insolvency. Dashboard showed ~$270 live portfolio; Kraken held ~$1,685.

**Fix merged (PR #65):** `load_live_usd_prices()` merges session anchor + live holdings.

### Lesson

- On any halt: **check Kraken directly** before `-resume-live`.
- Dashboard `/live` is advisory; Kraken UI is source of truth.

---

## 6. Complexity creep

Features enabled during live window (most should stay off until crypto spot is profitable):

| Feature | Risk |
|---------|------|
| **Triangular arbitrage** | 4-leg taker chains; largest live losses |
| **xStocks / equities** | TSLAx validation errors; 158-symbol expansion distraction |
| **50/50 crypto/equity buckets** | Paper ETH→USD trims labeled "crypto bucket >55%" mirrored live |
| **Futures paper sim** | `ENABLE_FUTURES=1` added noise; separate API keys |
| **Auditor + Gemini** | Config overrides, Discord spam (feature 062) |
| **Whale watch / follow** | Extra signals; follow disabled but watch ran |
| **Discord `-force`** | Bypass temptation during idle periods |

### Lesson

**Stage gates from handoff §8:**

1. Paper `cross_momentum` only  
2. Add `stat_arb` after 1 week  
3. Live single-hop ETH/ADA only  
4. Mirror only after 2 weeks clean live  
5. Equities/futures/triangular — **months later**

---

## 7. Discord visibility vs reality

| Discord showed | Reality |
|----------------|---------|
| Paper trade pins with positive edge | Live mirror DENY or skip |
| Portfolio PnL from paper book | Kraken wallet ±$65–135 from start |
| "VERIFY CONFIRM" tags | Edge metadata bugs (pre-075) |
| Heartbeat scan lines | Idle 56h — no qualifying net-positive route |
| Quiet mode toggles | Still noisy during auditor spam periods |

`logs/discord_chat.log` (~1.4 MB) captures the gap between **narrative** (bot is trading) and **Kraken fills** (mostly defensive + arb losses).

### Lesson

- Discord should show **live portfolio USD from Kraken** prominently when `LIVE_ENABLED=1`.
- Suppress paper trade pins in mirror mode or label **"PAPER ONLY — not mirrored"** explicitly.

---

## 8. What actually traded live — PnL reconstruction

### Trade inventory (from `.live_state.json`)

**22 live trades** (21 mirrored + 1 manual test), **~$10.38 total fees**.

| Strategy | Trades | Pattern |
|----------|--------|---------|
| cross_momentum | 10 | Mostly defensive sells to USD |
| triangular_arbitrage | 6 | 3–4 leg loops; **all negative** |
| portfolio_constraints | 4 | Bucket/cap trims |
| probe | 1 | ETH→BTC |
| manual | 1 | Connectivity test |

### Approximate economics

| Metric | Value |
|--------|-------|
| Opening session range | ~$1,650–1,724 |
| Peak recorded | $1,724 (Jun 15 handoff) |
| Pre-reset Kraken | **~$1,589** |
| Implied session loss | **~$65–135** (market + fees + bad arb) |
| Triangular arb contribution | **~$15–25** fees + slippage on 6 loops |
| False dashboard loss | ~$1,450 (bug — ignore) |

The `gain_loss` field sum (+$56) is **not meaningful** — it mixes accounting conventions (USD proceeds vs cost basis) and does not equal wallet delta.

### Did it make money?

**No.** Small net loss, mostly from:

1. Six triangular arb loops (Jun 16)  
2. Defensive momentum sells (churn + fees)  
3. Bucket trims mirroring paper allocation logic not tuned for ~$1.6k wallet  

It did **not** blow up the account. The damage was **death by complexity and fees**, not one bad order.

---

## 9. Actionable lessons for next live attempt

### Before arming live

- [ ] Rotate API keys; query+trade only  
- [ ] `scripts/anchor_paper_to_live.py --paper-only --clear-trades`  
- [ ] Verify `paper_baseline.json` matches Kraken  
- [ ] Paper-only **2 weeks minimum** with `cross_momentum,stat_arb` only  
- [ ] `pytest` green; `-verify` on last 20 paper trades  

### Minimal live profile (stage 3)

```env
LIVE_ENABLED=1
LIVE_TRADING_CONFIRM=I_ACCEPT_REAL_MONEY
LIVE_MIRROR_PAPER=0          # direct live only — no mirror confusion
LIVE_ALLOW_TRIANGULAR=0
LIVE_MAX_ROUTE_LEGS=1
LIVE_ALLOWED_ASSETS=ETH,ADA,USD
LIVE_MAX_USD_PER_TRADE=50
LIVE_DRAWDOWN_HALT_PCT=0.10
LIVE_STRICT_PROFIT=1
PROFIT_ONLY_MODE=1
ENABLE_EQUITIES=0
ENABLE_FUTURES=0
DCA_ENABLED=0
AUDITOR_ENABLED=0
STRATEGIES=cross_momentum
```

### Operational rules

1. **One config change per day** — document in feature log  
2. **Kraken UI check** on every halt before resume  
3. **No triangular, no `-force`, no auditor** until single-hop profitable  
4. Re-anchor paper after every live session: `anchor_paper_to_live.py --paper-only`  
5. Compare wallet to `paper_baseline.json` — not paper PnL  

### Reset artifacts (2026-06-24)

| Item | Location |
|------|----------|
| Archive snapshot | `archive/paper-live-reference-2026-06-24/` |
| Kraken baseline | `paper_baseline.json` (gitignored) |
| Anchor script | `scripts/anchor_paper_to_live.py --paper-only` |
| Env knobs | `PAPER_RESET_BASELINE_PATH`, `RESET_PAPER_TO_BASELINE` |

---

## Related documents

- `docs/PROJECT_HANDOFF.md` — canonical handoff (2026-06-16)  
- `feature_logs/051_live-kraken-trading.md` — go-live  
- `feature_logs/072_live-valuation-false-halt.md` — valuation bug  
- `feature_logs/075_live-mirror-edge-fix.md` — edge-before-mirror fix  
- `feature_logs/082_paper-only-baseline-reset.md` — this reset  

---

*Generated 2026-06-24 after paper-only baseline reset. Kraken truth: ~$1,589 total (ETH ~$1,168 + USD ~$416).*
