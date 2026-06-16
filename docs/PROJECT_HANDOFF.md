# TradeBot — Project Handoff (2026-06-16)

> **Purpose:** Single reference for picking up this project after a full reset — new API keys, simpler strategy set, and a clean mental model of what happened.
>
> **Do not commit secrets.** Rotate Kraken keys before any restart. This file contains no API keys.

---

## 1. Project purpose

**TradeBot** is a Python Kraken trading bot (`main.py`) that:

| Component | Role |
|-----------|------|
| **Trading engine** | Poll loop (`POLL_INTERVAL`, default 15s); orchestrates strategies, risk gates, paper or live execution |
| **Strategies** | `cross_momentum`, `stat_arb`, `triangular_arbitrage`, `equity_dca` (when enabled) |
| **Paper broker** | Simulated fills in `.paper_state.json` / `paper_portfolio.json` using live Kraken prices |
| **Live broker** | Real Kraken spot orders when `LIVE_ENABLED=1` + confirm phrase; state in `.live_state.json` |
| **Live mirror** | Paper runs continuously; profitable paper routes mirror to Kraken when gates pass (`LIVE_MIRROR_PAPER=1`) |
| **Discord** | Owner commands (`TradeBot -portfolio`, `-force`, `-resume-live`, etc.) + alerts |
| **WatchDog** | In-process monitor: parses logs/receipts, health score, drawdown warnings, auto-pause |
| **Auditor** | Scheduled + event-driven reviews; Gemini chat optional; writes `reports/YYYY-MM-DD/` |
| **Dashboard** | Local read-only UI at `http://127.0.0.1:8765` — `/paper` and `/live` split views |

**Design goals** (see `docs/architecture/overview.md`): fee-positive trades, ETH reserve + alt caps, 10% drawdown circuit breaker, observable via Discord/logs/receipts.

---

## 2. Timeline — major phases

Chronological arc from first engagement through emergency halt on **2026-06-16**.

### Phase A — Foundation (May – early June 2026)

- Initial bot upload, CI/pytest workflow, feature-log system, version history
- Architecture docs (`docs/architecture/`), naming conventions, verification protocol
- Local dashboard v2, trader command-center UX
- Unblocked triangular arb + stat_arb signals (#36)
- Singleton PID lock (#37) — prevent duplicate bot instances
- Auditor bot + auto-apply confirm/restart (#38–#39)
- Whale watch + whale-follow trading (#40–#41)
- Goal evolution tiers + crash-hold guard (#42)
- Windows Task Scheduler auto-start (#43)

### Phase B — Paper trading maturity (June 10–12)

- Discord chatter reduction (#44)
- Independent trade verifier + `-verify` command (#45–#47)
- Real-time verify tags + quiet Discord mode (#48)
- Fix adaptive suspension leaving bot stuck (#49)
- Net-positive tuning, idle probe mode, forced active trading (features 026–030)

### Phase C — Go live ADA/ETH (June 13–14)

- **Feature 051 / PR #50:** Live Kraken trading with `LIVE_TRADING_CONFIRM=I_ACCEPT_REAL_MONEY`
- Initial scope: single-hop **ETH/USD** and **ADA/USD** only; `LIVE_MIN_ETH_RESERVE=0.5`
- **10% portfolio drawdown halt** from session peak (`LIVE_DRAWDOWN_HALT_PCT=0.10`)
- Paper shadow + live mirror mode introduced
- Quiet Discord profile for live sessions (trades, halts, errors only)
- First live connectivity test + mirror fills; session anchored ~**$1,653–1,724** portfolio

### Phase D — Live mirror ramp (June 15)

- Auditor paper vs live PnL labels (#51–#52)
- Confidence-gated mirror: CONFIRM / UNCERTAIN / DENY tags (#54–#56)
- **Kraken xStocks (tokenized equities) v1** — 6-symbol watchlist (#55 / feature 057)
- **Equity DCA** parallel to crypto triangular arb (#57 / feature 060)
- **4-leg triangular live mirror** unblocked (`LIVE_MAX_ROUTE_LEGS=4`, #58)
- **Paper anchor to live** on startup — fix paper ~$12k vs live ~$1.6k divergence (#59)
- Auditor sync + profit-only enforcement (#56 / feature 058)
- Max Kraken profile: equities live path, futures paper sim (#59 feature log)
- Auditor Discord spam triage (#62); idle visibility scan line (#68)

### Phase E — Portfolio expansion (June 16 morning)

- **50/50 crypto/equity bucket strategy** (#63 / feature 070)
- **Discord `-force` command** — best offensive route through all gates (#61)
- **Expand xStock universe** to all 158 online USD pairs + NVDAx/AMDx preference (#64, **open**)
- Live error fixes: TSLAx validation, UNI/BTC route halt, force-trade edge (#62, **open**)

### Phase F — Crisis and emergency halt (June 16 afternoon)

1. **Valuation bug (feature 072 / PR #65):** Dashboard and circuit breaker priced ETH at **$0** because paper had sold all ETH while live still held ~0.79 ETH. Showed **~84% false drawdown** → **LIVE HALT** while Kraken balance was intact (~$1,685).
2. **Real session loss ~$40** from peak $1,724 (triangular arb slippage + fees ~$5–10, not $1,453).
3. **UNI/BTC insufficient-funds route halt** on multi-hop live path.
4. User **stopped all processes**, disabled scheduler, set safe `.env` flags (see §7).

**Fix merged:** PR #65 — `load_live_usd_prices()` merges session anchor + live holdings; engine fetches union of paper+live assets. **Halt flag may still be set** — user must explicitly `-resume-live` after review.

---

## 3. Merged pull requests (#43–#61, #63, #65)

| PR | Feature | Summary |
|----|---------|---------|
| **#43** | 043 | Windows Task Scheduler auto-start; `-IncludeDashboard` for dashboard autostart |
| **#44** | 044 | Reduce Discord whale alert chatter |
| **#45** | 045 | Independent trade verifier (paper-to-live audit path) |
| **#46** | 046 | Raise whale watch thresholds to $1M default |
| **#47** | 047 | Verifier multi-hop fee checks + `docs/path-to-live-trading.md` |
| **#48** | 048 | Live trade verify tags + quiet Discord mode |
| **#49** | 049 | Fix adaptive suspension stuck at strict edge thresholds |
| **#50** | 051 | **Live Kraken trading** — confirm gate, ADA/ETH restrictions, drawdown halt |
| **#51** | 053 | Auditor reports label paper vs live Kraken PnL |
| **#52** | 054 | Auditor Discord UX — forecast clarity, news links, batch confirm, attachments |
| **#53** | 055 | WatchDog live gain alerts use Kraken spot when live armed |
| **#54** | 056 | Confidence-gated live mirror (`LIVE_MIRROR_MIN_CONFIDENCE`) |
| **#55** | 057 | **Kraken xStocks spot** — tokenized equities v1, `ENABLE_EQUITIES` |
| **#56** | 058 | Auditor sync labels + profit-only trading enforcement |
| **#57** | 060 | **Equity DCA** alongside crypto triangular arbitrage |
| **#58** | 063 | Resume live fills — 4-leg triangular mirror, DCA live USD hint |
| **#59** | 065 | **Paper anchor to live** in mirror mode (`PAPER_ANCHOR_TO_LIVE`) |
| **#60** | 066 | Fix live mirror losses + auditor double-post dedupe |
| **#61** | 067 | **`TradeBot -force`** Discord command |
| **#63** | 070 | **50/50 crypto/equity portfolio** + live error fixes |
| **#65** | 072 | **Fix live portfolio valuation false drawdown halt** |

Earlier merged work (context): #28 dashboard v2, #27 local dashboard, #36 arb unblock, #37 singleton lock, #38–#42 auditor/whale/goals.

---

## 4. Open PRs and branches at halt time

| PR | Branch | State | Notes |
|----|--------|-------|-------|
| **#64** | `feature/expand-xstock-universe` | **OPEN** | 158 xStocks, NVDAx/AMDx preference, `LIVE_EQUITY_AUTO_ALLOW`; **current checkout** |
| **#62** | `feature/fix-live-errors-money` | **OPEN** | TSLAx filter, route preflight, multihop force edge, `-resume-live` |

**Draft PRs (ignore unless reviving):** #33–#37 cursor test/coverage branches.

**Local main** was behind remote at handoff writing time; **PR #65 is on `origin/main`**. Pull before restarting:

```powershell
git checkout main
git pull origin main
```

---

## 5. What worked

- **Live Kraken fills** — ~17 successful live mirror/session fills (June 14–16); receipts in `receipts/`, detail in `.live_state.json`
- **Safety rails that fired correctly (when data was right):**
  - `LIVE_DRAWDOWN_HALT_PCT=0.10` — 10% halt concept validated (also triggered falsely once — see §6)
  - `LIVE_MIN_ETH_RESERVE=0.5` — ETH floor preserved (~0.79 ETH at halt)
  - `LIVE_STRICT_PROFIT` / profit-only — blocked negative-net UNI/cross routes on live
- **Independent verifier + live_tag** — CONFIRM/UNCERTAIN/DENY gating reduced blind mirrors
- **Kraken xStocks API access** — probe validated 158 online USD pairs (`scripts/probe_xstocks.py`, `logs/xstocks_probe.json`)
- **Paper anchor (#59)** — correct direction for mirror-mode sanity (paper still diverges mid-session)
- **Quiet Discord mode** — usable once auditor spam was tuned (#62)
- **Dashboard `/live` vs `/paper`** — split views helped see divergence
- **Feature logs + version history** — 72 numbered feature logs in `feature_logs/` trace every request

---

## 6. What failed or hurt UX

| Issue | Impact |
|-------|--------|
| **Paper/live divergence** | Paper book showed ~$12k while live ~$1.7k; misleading PnL, auditor confusion, false confidence |
| **Valuation bug (072)** | ETH priced $0 → **false 84% drawdown halt** while Kraken held cash + ETH |
| **Triangular arb on live** | Real losses ~$5–10 + fees; sequential 4-leg paths amplify slippage vs paper instant fill |
| **UNI/BTC insufficient funds** | Mid-route live halt when leg-2 sizing didn't match chain balances |
| **TSLAx verifier false negatives** | Mirror spam / skips until equity watchlist validation (PR #62) |
| **Auditor Discord spam** | Scheduled audits + low-severity proposals; partially fixed (#62, #60) |
| **Bot appearing idle** | Quiet mode + negative-net skips + hourly caps → no visible activity; scan line added (#68) |
| **Complexity** | Too many parallel features: live mirror + triangular + xStocks + DCA + 50/50 + futures paper + force + auditor chat |
| **Negative net floor experiment (052)** | Temporary `MIN_NET_PROFIT_PCT=-0.002` increased fee bleed risk on live |
| **158 xStock expansion (#64)** | Rate limits, scan rotation, position caps — untested at production scale before halt |

---

## 7. Final state at halt (2026-06-16)

### Processes

- **All TradeBot / dashboard / scheduler processes stopped**
- **Windows Task Scheduler task disabled** (user action)

### `.env` safe mode (user-set; do not commit `.env`)

```env
LIVE_ENABLED=0
LIVE_MIRROR_PAPER=0
DCA_ENABLED=0
AUDITOR_ENABLED=0
```

(Re-enable selectively per §8 checklist.)

### Kraken spot (approximate at halt)

Source: `live_session_start.json` anchor + `.live_state.json` sync.

| Asset | Amount | Notes |
|-------|--------|-------|
| **ETH** | ~0.79 | Above 0.5 floor |
| **USD** | ~$266 | |
| **ADA** | ~24.5 | |
| **Portfolio USD** | **~$1,683** | ETH @ ~$1,823 + cash + alts |
| **Session peak** | **$1,724.27** | Anchored 2026-06-15 10:33 PDT |
| **Real session loss** | **~$40** | Mostly arb + fees, not catastrophic drawdown |

### Paper simulation

- **Do not trust paper PnL** for live decisions — separate inflated book even after anchor
- `.paper_state.json` may show divergent holdings (DOT/UNI/etc. paper-only routes)

### Halt flags

- Live broker / circuit breaker may still show **halted** in `.live_state.json`
- After fixing valuation (#65 on main), user must run `TradeBot -resume-live` in Discord (or clear halt in state) **only after confirming Kraken balance**

### Key state files (backup before delete)

| File | Purpose |
|------|---------|
| `.live_state.json` | Live balances, trades, halt flag |
| `.paper_state.json` | Paper sim state |
| `live_session_start.json` | Session anchor, peak, halt threshold |
| `runtime_overrides.json` | Auditor-applied overrides |
| `.tradebot_goals_state.json` | Goal evolution progress |
| `.dca_state.json` | Equity DCA schedule |
| `overnight_handoff.json` | Stale overnight snapshot (2026-06-14) — see updated pointer |

---

## 8. Starting fresh — checklist

### Security first

- [ ] **Rotate Kraken API keys** in Kraken UI; update `.env` `KRAKEN_API_KEY` / `KRAKEN_API_SECRET`
- [ ] Confirm key permissions: **Query + Trade only** — never Withdraw
- [ ] Revoke any keys pasted in chat history

### Archive and reset state

```powershell
# Backup first
New-Item -ItemType Directory -Force -Path archive/2026-06-16-halt
Copy-Item .live_state.json, .paper_state.json, live_session_start.json, runtime_overrides.json, .tradebot_goals_state.json -Destination archive/2026-06-16-halt/ -ErrorAction SilentlyContinue

# Reset (after backup)
Remove-Item .paper_state.json, .live_state.json, runtime_overrides.json -ErrorAction SilentlyContinue
# Or set RESET_PAPER_STATE=1 / RESET_LIVE_STATE=1 once on next start — see .env.example
```

- [ ] Reset `live_session_start.json` (delete or let engine re-anchor on next live session)
- [ ] Review `archive/` before deleting receipts/logs if needed for taxes

### Choose operating mode

**Recommended: paper-only first, then live single-hop only**

| Stage | Settings | Strategies |
|-------|----------|------------|
| **1. Paper baseline** | `LIVE_ENABLED=0`, `LIVE_MIRROR_PAPER=0` | `cross_momentum` only |
| **2. Paper + verifier** | Run 1–2 weeks; use `-verify` and dashboard | Add `stat_arb` if stable |
| **3. Live single-hop** | `LIVE_ENABLED=1`, confirm phrase, `LIVE_ALLOW_TRIANGULAR=0`, `LIVE_MAX_ROUTE_LEGS=1` | `cross_momentum` on ETH/ADA only |
| **4. Optional mirror** | `LIVE_MIRROR_PAPER=1`, `PAPER_ANCHOR_TO_LIVE=1`, `LIVE_MIRROR_MIN_CONFIDENCE=confirm` | Still no triangular on live |
| **5. Later** | Equities/DCA only after crypto stable | `ENABLE_EQUITIES=1`, `DCA_ENABLED=1` separately |

**Defer until proven:** live triangular arb, 158 xStock universe, futures live, negative net-profit floor, `-force` in live mode.

### Code baseline

```powershell
git checkout main
git pull origin main   # includes PR #65 valuation fix
# Optional: merge PR #62 fixes without #64 expansion
# Optional: cherry-pick valuation + TSLAx fixes only
```

### Re-enable services (when ready)

1. [ ] Set `.env` flags one at a time; restart via `.\scripts\start_tradebot.ps1`
2. [ ] Dashboard: `http://127.0.0.1:8765/live`
3. [ ] Discord: `TradeBot -portfolio` — confirm live USD matches Kraken
4. [ ] **Auditor last** — `AUDITOR_ENABLED=1` only after trading stable; keep `AUDITOR_DISCORD_QUIET=1`
5. [ ] **Scheduler last** — re-enable Windows Task Scheduler only when confident

### Suggested minimal `.env` profile (fresh start)

```env
LIVE_ENABLED=0
LIVE_MIRROR_PAPER=0
DCA_ENABLED=0
ENABLE_EQUITIES=0
ENABLE_FUTURES=0
AUDITOR_ENABLED=0
STRATEGIES=cross_momentum
PROFIT_ONLY_MODE=1
LIVE_DRAWDOWN_HALT_PCT=0.10
LIVE_MIN_ETH_RESERVE=0.5
DISCORD_QUIET_MODE=1
CIRCUIT_BREAKER_ENABLED=1
```

---

## 9. Key config reference

### Critical env vars

| Variable | Default / note | Doc |
|----------|----------------|-----|
| `KRAKEN_API_KEY` / `KRAKEN_API_SECRET` | Required for live | `.env.example` |
| `LIVE_ENABLED` | `0` — master live switch | `docs/live-trading.md` |
| `LIVE_TRADING_CONFIRM` | Must be `I_ACCEPT_REAL_MONEY` to arm | `docs/live-trading.md` |
| `LIVE_MIRROR_PAPER` | Paper shadow + mirror to Kraken | `docs/live-trading.md` |
| `PAPER_ANCHOR_TO_LIVE` | Sync paper to live on startup | `docs/live-trading.md` |
| `LIVE_DRAWDOWN_HALT_PCT` | `0.10` — 10% peak drawdown halt | `docs/live-trading.md` |
| `LIVE_MIN_ETH_RESERVE` | `0.5` ETH floor | `docs/live-trading.md` |
| `LIVE_ALLOW_TRIANGULAR` | `0` recommended for fresh start | `docs/live-trading.md` |
| `LIVE_MAX_ROUTE_LEGS` | Was `4` at halt; use `1` fresh | `docs/live-trading.md` |
| `LIVE_STRICT_PROFIT` | `1` — no adaptive relaxation on live | `docs/live-trading.md` |
| `PROFIT_ONLY_MODE` | `1` — block negative-net offensive trades | `.env.example` |
| `STRATEGIES` | Comma list | `.env.example` |
| `ENABLE_EQUITIES` | xStocks spot | `docs/kraken-equities-futures.md` |
| `DCA_ENABLED` | Scheduled equity buys | `docs/dca-equities.md` |
| `ENABLE_FUTURES` | Paper/live futures sim | `docs/kraken-equities-futures.md` |
| `DISCORD_QUIET_MODE` | Suppress paper/noise | feature 051 notes |
| `AUDITOR_ENABLED` | AI audit scheduler | `docs/architecture/modules.md` |
| `WATCHDOG_ENABLED` | Health monitor | `.env.example` |

### Important paths

| Path | Purpose |
|------|---------|
| `main.py` | Entry point |
| `bot/engine.py` | Tick loop, mirror, halt logic |
| `bot/live_broker.py` | Real Kraken execution |
| `bot/live_portfolio.py` | Live USD valuation (post-#65) |
| `bot/paper_anchor.py` | Paper←live sync |
| `dashboard/` | Local web UI |
| `watchdog/` | WatchDog service |
| `bot/auditor_service.py` | Auditor |
| `docs/live-trading.md` | Live arm/disarm guide |
| `docs/dca-equities.md` | DCA + 50/50 buckets |
| `docs/kraken-equities-futures.md` | xStocks + futures |
| `docs/independent-verification.md` | Verifier |
| `docs/auto-start-windows.md` | Task Scheduler |
| `feature_logs/` | Numbered change history (001–072+) |
| `feature_logs/072_live-valuation-false-halt.md` | Valuation bug postmortem |
| `logs/runtime.log` | Primary runtime log |
| `logs/live_mirror_skips.log` | Mirror skip reasons |
| `receipts/` | Per-trade receipts |
| `reports/` | Auditor markdown reports |
| `scripts/start_tradebot.ps1` | Start/restart bot |
| `scripts/probe_xstocks.py` | xStock catalog probe |
| `scripts/anchor_paper_to_live.py` | One-shot paper re-anchor |
| `scripts/is_tradebot_running.py` | PID check |

### Discord commands (owner)

| Command | Action |
|---------|--------|
| `TradeBot -portfolio` | Holdings, PnL, scan activity line |
| `TradeBot -force` | Best gated offensive route (respects halt) |
| `TradeBot -resume-live` | Clear live halt after manual review |
| `TradeBot -reset` | Reset paper (anchors to live if mirror mode) |
| `WatchDog -verify` | Run independent verifier |

---

## 10. Feature log index (high-signal entries)

| ID | Topic |
|----|-------|
| 051 | Live Kraken trading |
| 052 | Negative net-profit floor (action hour) |
| 059 | Max Kraken profile |
| 060 | Equity DCA + triangular |
| 062 | Auditor spam triage |
| 063 | Resume live 4-leg mirror |
| 065 | Paper anchor to live |
| 067 | Discord `-force` |
| 068 | Idle scan visibility |
| 069 | Live errors (TSLAx, UNI halt) |
| 070 | 50/50 portfolio |
| 071 | Expand xStock universe |
| 072 | Valuation false halt (merged #65) |

Full list: `feature_logs/README.md`.

---

## 11. Verification commands (after restart)

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\is_tradebot_running.py
.\scripts\start_tradebot.ps1
# Dashboard
Start-Process "http://127.0.0.1:8765/live"
```

---

## 12. Related handoff artifacts

| File | Status |
|------|--------|
| **`docs/PROJECT_HANDOFF.md`** | This document (canonical) |
| `overnight_handoff.json` | Updated pointer to this doc; stale 2026-06-14 trading snapshot |
| `feature_logs/073_project-handoff.md` | Brief feature-log entry for this doc |
| `live_session_start.json` | Session anchor at last live run (local, untracked) |

---

*Generated 2026-06-16 for project reset. Pull `main` (includes PR #65) before acting on trading config.*
