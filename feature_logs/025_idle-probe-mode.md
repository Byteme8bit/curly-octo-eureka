# 025 — Idle probe mode (visible "it's trying" within 15–30 min)

**Requested:** 2026-05-30
**Status:** awaiting verification — pytest passing locally (272), live Discord smoke test pending

## Request
> If no trades happen within 15–30 minutes, I want the bot to just do something
> for the sake of me seeing it trying — change the strategy, try a small
> hail-mary trade, or something.

## Approach
The bot already had an "adaptive relaxation" mechanism (`IDLE_REEVAL_HOURS`), but
it engaged after **2 hours** and decayed so slowly it reached its loosest stance
only ~6h later — invisible on a 15–30 min horizon. This request speeds it up and
makes it visible, reusing the existing machinery instead of a parallel system.

## What changed

### 1. Relaxation bites fast (`bot/adaptive.py`)
`compute_relax_factor` decay raised from `0.083/hr` (≈6h to half-strictness) to
`_RELAX_PER_HOUR = 2.0`. With a 15 min threshold it now reaches the `0.5` floor
(edges loosened to fee break-even) by ~30 min total idle — squarely in the
requested window.

### 2. Fires within the window (`.env`)
- `IDLE_REEVAL_HOURS=0.25` (start hunting at 15 min; fully relaxed by ~30 min).
- `IDLE_REEVAL_MAX_ATTEMPTS=6` (keeps probing instead of giving up after 3).

### 3. Visible "hunting" message (`bot/risk.py`)
`check_adaptive_notification` reworded to **"Probe mode — hunting a trade 🎯"**,
shows the idle time in minutes, the current relaxed thresholds, and states it
will take a small probe trade on the best candidate that still clears costs.

## Deliberate limit (and why)
Probes still respect the **fee floor** — the bot will take the *smallest
break-even-clearing* trade, but not a guaranteed-losing one. We just (req 024)
raised `MIN_TRADE_EDGE` to stop fee-bleed; forcing sub-break-even "hail marys"
would re-introduce guaranteed losses and teach us nothing, even on paper. If the
market is genuinely flat, no candidate clears costs and the bot posts the
"hunting" status instead of forcing a loser — so you still *see* it trying.

**Follow-up available:** a `IDLE_PROBE_ALLOW_BELOW_BREAKEVEN` toggle could let it
take a true sub-cost hail-mary for pure visibility. Not built — say the word.

## Files changed
- **Modified** `bot/adaptive.py` — faster relax decay (`_RELAX_PER_HOUR`).
- **Modified** `bot/risk.py` — "probe mode" notification copy.
- **Modified** `.env` (gitignored) — `IDLE_REEVAL_HOURS=0.25`, `IDLE_REEVAL_MAX_ATTEMPTS=6`.
- **Added** `tests/test_adaptive.py` — 6 tests for the curve + fee-floor clamp.

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest -q     # 272 passing locally
```
Live: restart the bot, leave it idle; within ~15 min you should see the
"Probe mode — hunting a trade" message, then a small probe trade if any setup
clears costs.
