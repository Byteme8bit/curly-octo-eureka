# 082 — Paper-only baseline reset from Kraken

**Requested:** 2026-06-24
**Status:** awaiting verification - pytest pending

## Request
Restart in PAPER-ONLY mode with fresh baseline from real Kraken, archive old data, add reset variable, and deep analysis report.

## Actions taken
- Extended `bot/paper_anchor.py` with `save_paper_baseline` / `load_paper_baseline`
- Extended `scripts/anchor_paper_to_live.py` with `--paper-only`, `--clear-trades`, `--no-baseline`
- Added `PAPER_RESET_BASELINE_PATH` and `RESET_PAPER_TO_BASELINE` to `config.py` / `.env.example`
- Archived state to `archive/paper-live-reference-2026-06-24/`
- Updated `.env` for paper-only conservative profile (not committed)
- Wrote `docs/LIVE_ATTEMPT_POSTMORTEM.md`

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_paper_anchor.py -q
.\.venv\Scripts\python.exe scripts\anchor_paper_to_live.py --paper-only --clear-trades
.\scripts\start_tradebot.ps1
.\.venv\Scripts\python.exe scripts\is_tradebot_running.py
```

## Notes
- `paper_baseline.json` is gitignored; re-run anchor script before each future live attempt.
- Kraken snapshot at reset: ~$1,589 portfolio (ETH ~$1,168 + USD ~$416).
