# 100 — Resume paper activity (maker + ADA seed)

**Requested:** 2026-08-07 05:06 PDT
**Status:** complete (VPS applied; pytest pending locally)

## Request
PERMISSION GRANTED: resume paper activity (maker fee rate + ADA seed + idle 20m + multi-hop maker)

## Actions taken
- `bot/engine.py` — `PAPER_USE_MAKER_FEES` applies to multi-hop paper preflight (not 1-hop only)
- `scripts/paper_activity_watchdog.py` — default idle 20m; when maker on, align `FEE_RATE` to maker floor
- `deploy/systemd/tradebot-activity-watch.service` — `PAPER_ACTIVITY_IDLE_MINUTES=20`
- VPS: `FEE_RATE=0.0016`, seed **$100 USD → ~497 ADA**, archive `archive/2026-08-07-resume-maker-ada/`, restart tradebot + timer
- Post-apply: trades **120**, ADA ~**1197**, required_edge_1hop **0.0035**, `FEE_FORCE_STATIC=0`

## Verification
awaiting verification - pytest pending

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

VPS applied: trades already 120; watch for further fills under maker hurdles.

## Notes
Keeps `FEE_FORCE_STATIC=0`. Paper uses maker schedule for estimates/execution via `FEE_RATE`; live still uses public FeeEngine when enabled.
