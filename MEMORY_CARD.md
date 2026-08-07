# Memory card — eth-trading-bot

**Last updated:** 2026-08-07 PDT (100 resume paper maker + ADA seed)  
**Read this first** before answering prompts about this repo.

---

## What this is

Python Kraken **spot** trading bot (paper + optional live). Strategies, safety rails, Discord, local dashboard (`http://127.0.0.1:8765`). **Not options** — buy/sell crypto pairs only.

---

## Current state (Aug 2026 revival)

| Item | Value |
|------|--------|
| **Mode** | Paper-only on VPS (`tradebot.service`) — local Windows bot stopped |
| **Strategy** | `cross_momentum`, `stat_arb`, `triangular_arbitrage` (paper maker ~0.16%; public FeeEngine kept) |
| **Branch** | `cb/vps-deploy` |
| **VPS** | `mail.lynch.gdn` / `cursor@172.245.39.184` — `scripts/deploy_to_vps.ps1` |
| **Dashboard URL** | https://lynch.gdn/tradebot/ (nginx + basic auth; backend `127.0.0.1:8765`) |
| **Baseline** | Screenshot ETH **0.52042** kept; USD seeded into ADA/BTC/SOL for arb (094) — cash/alts ≠ screenshot |
| **Archive** | `archive/2026-08-07-arb-inventory-seed/` (094); prior restore archive also present |
| **Trades** | Active after 095 (paper maker preflight + low slippage); watchdog timer every 15m |
| **Fees** | `FEE_FORCE_STATIC=0`; paper uses **maker** (`FEE_RATE=0.0016`, multi-hop preflight) when `PAPER_USE_MAKER_FEES=1` |
| **Kraken keys** | Optional for paper; needed for live/anchor |
| **Discord** | Enabled if credentials in `.env` (086) |
| **Dashboard** | `scripts/start_dashboard.ps1` — separate process, port 8765 |

### Active `.env` tuning (VPS / local, not committed)

- `FEE_RATE=0.0016`, `FEE_FORCE_STATIC=0`, `PAPER_USE_MAKER_FEES=1`, `SLIPPAGE_BUFFER_PCT=0.0001`
- `PAPER_ACTIVITY_IDLE_MINUTES=20` (systemd unit + default)
- `STRATEGIES=cross_momentum,stat_arb,triangular_arbitrage`, `PROFIT_ONLY_MODE=1`
- `DUST_USD=5`, `PAPER_ANCHOR_TO_LIVE=0`
- Watchdog: `tradebot-activity-watch.timer` → `scripts/paper_activity_watchdog.py`

**Notes:** (100) ~$100 USD → ADA reseed; paper maker multi-hop; idle nudge at 20m. ETH may be ~0.5 after ETH→ADA fills (not screenshot-locked). Never fakes static fees.

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

- [ ] Validate paper PnL vs baseline for 1–2 weeks under real 0.40% fees
- [ ] Live only after validation — `apply_revival_profile.py live`

---

## Recent feature logs

| ID | Topic |
|----|--------|
| 100 | Resume paper maker fee + ADA seed + multi-hop ✓ |
| 097 | Holdings qty display + honest session PnL ✓ |
| 096 | Dashboard trade count + closed-loop PnL ✓ |
| 095 | Paper maker fees + activity watchdog ✓ |
| 094 | Seed USD arb inventory + tighter stat-arb ✓ |
| 093 | Restore Kraken screenshot baseline ✓ |
| 090 | Public `/tradebot` dashboard path |
| 088 | Real 0.40% fees + paper baseline reset ✓ |
| 083 | Dashboard trades chart fix ✓ |

See `feature_logs/` for full list.
