# Memory card — eth-trading-bot

**Last updated:** 2026-08-04 PDT  
**Read this first** before answering prompts about this repo.

---

## What this is

Python Kraken **spot** trading bot (paper + optional live). Strategies, safety rails, Discord, local dashboard (`http://127.0.0.1:8765`). **Not options** — buy/sell crypto pairs only.

---

## Current state (Aug 2026 revival)

| Item | Value |
|------|--------|
| **Mode** | Paper-only, bot running |
| **Strategy** | `cross_momentum` only |
| **Branch** | `cb/goal-state-null-fix` (commit `e954391` — goal-state null fix, not pushed at last check) |
| **Baseline** | `paper_baseline.json` — ~$1,397.51 (ETH 0.52042, USD 415.90, ADA 24.602263) anchored 2026-08-04 |
| **Archive** | `archive/2026-08-04-revival/` — pre-revival state backup |
| **Trades so far** | 2 defensive ETH→USD bucket trims (not momentum rotations) |
| **Why mostly HOLD** | 0.40% taker fees (no API keys = public tier); best route ~+0.0036 edge vs +0.0040 fee hurdle; `PROFIT_ONLY_MODE=1` |
| **Kraken keys** | Not in `.env` yet — paper works on public prices; keys needed for live/anchor |
| **Dashboard** | Fixed 2026-08-04 (feature 083) — trades chart uses grouped bars + caption; cache `app.js?v=048` |

### Active `.env` tuning (local, not committed)

Approximate revival tuning after conservative start:

- `DAY_TRADER_MODE=1`, `CRYPTO_DAY_TRADE_MODE=1`
- `MIN_TRADE_EDGE=0.002`, `FEE_SAFETY_MULTIPLIER=1.0`, `TRADE_COOLDOWN=45`
- `MAX_CRYPTO_BUCKET_PCT=0.80`, `CRASH_HOLD_ENABLED=0`
- `LIVE_ENABLED=0`, `AUDITOR_ENABLED=0`, `ENABLE_EQUITIES=0`, `ENABLE_FUTURES=0`

**Incident history:** `.env` was once wiped to 0 bytes — rebuild via `apply_revival_profile.py`. Crash-hold blocked trades until goals state reset + `CRASH_HOLD_ENABLED=0`.

---

## Revival plan (phased)

Use `scripts/apply_revival_profile.py`:

1. **phase1** — Paper-only, `cross_momentum`, no live/equities/auditor/day-trader
2. **phase2** — Add `DAY_TRADER_MODE=1` after ~48h stable paper run
3. **live** — Single-hop ETH/ADA only, $25 cap, 5 trades/day, 10% drawdown halt — **only after 1–2 weeks positive paper PnL**

Full history: `docs/PROJECT_HANDOFF.md` §8 checklist.

---

## User preferences (agent behavior)

- **Branches:** prefix `cb/` for new work
- **Commits:** only when explicitly asked
- **Edits:** propose changes and ask permission first — unless prompt starts with `PERMISSION GRANTED:`
- **Verification:** agent shell may be sandbox-locked — leave `awaiting verification - pytest pending` and give exact commands for user to run
- **Billing:** be concise; no casual chat — direct conversational stuff to other chatbots
- **Version history:** snapshot every **modified existing file** at end of request via `scripts/version_history.py` with feature-log `--request-id`
- **Feature logs:** one numbered file per user request in `feature_logs/`

---

## Key paths

| Path | Purpose |
|------|---------|
| `.env` | Runtime config (gitignored, may hold secrets) |
| `.paper_state.json` | Paper portfolio + trades |
| `.tradebot_goals_state.json` | Goals / crash-hold state |
| `paper_baseline.json` | Anchor snapshot for validation |
| `logs/trade_diagnosis.json` | Why trades blocked |
| `receipts/` | Trade receipt `.txt` files |
| `scripts/start_tradebot.ps1` | Start bot |
| `scripts/start_dashboard.ps1` | Start dashboard :8765 |
| `scripts/anchor_paper_to_live.py --paper-only` | Sync paper to Kraken (needs API keys) |

---

## Common commands

```powershell
.\scripts\start_tradebot.ps1
.\scripts\start_dashboard.ps1
.\.venv\Scripts\python.exe scripts\is_tradebot_running.py
.\.venv\Scripts\python.exe scripts\apply_revival_profile.py phase1   # or phase2 / live
.\.venv\Scripts\python.exe -m pytest -q
Invoke-RestMethod http://127.0.0.1:8765/api/paper/trades/series
```

---

## Gotchas

- **Never commit** `.env`, state files, or API keys
- **June paper history** inflated portfolio (~$7.8k/day PnL) — dashboard filters chart to `>= 2026-08-01` for revival window
- **Bucket trims** can fire before momentum rotations when crypto % > target
- **`GoalEvolutionState.load()`** null portfolio crash fixed on `cb/goal-state-null-fix`
- **PowerShell:** use `Invoke-RestMethod`, not `curl -s`
- **One config change per day max** during paper validation

---

## Open / next steps

- [ ] Add Kraken API keys to `.env` when ready for anchor/live
- [ ] 1–2 week paper validation vs `paper_baseline.json`
- [ ] Optional: `MIN_TRADE_EDGE=0.0035` to unblock ETH→UNI (user must approve)
- [ ] Push `cb/goal-state-null-fix` when ready
- [ ] Live only after validation pass — use `apply_revival_profile.py live`

---

## Recent feature logs

| ID | Topic |
|----|--------|
| 074 | Conservative restart |
| 082 | Paper baseline reset |
| 083 | Dashboard trades chart fix ✓ |
| 081 | Live spot mirror unblock |
| 080 | Discord futures visibility |

See `feature_logs/` for full list.
