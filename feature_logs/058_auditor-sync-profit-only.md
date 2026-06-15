# 058 — Auditor sync labels + profit-only YOLO

**Requested:** 2026-06-15
**Status:** awaiting verification — pytest pending

## Request
Auditor report numbers look out of sync (paper vs live, strategy sums, drawdown,
session PnL). Clarify reporting without faking live PnL. Enable aggressive
trading only when trades are net-profitable after fees.

## Actions taken
- `bot/auditor/report.py` — live Kraken block leads when `LIVE_ENABLED`; paper
  labeled simulation-only; strategy table uses gross PnL with non-additive note;
  split paper vs live drawdown; forecast titled as paper-only projection.
- `dashboard/service.py` — `dual_summary` (paper + live strips) when mirror mode.
- `config.py` — `PROFIT_ONLY_MODE`, `YOLO_PROFITABLE` settings.
- `bot/risk.py` — profit-only floor never negative.
- `bot/engine.py` — hard block offensive net ≤ 0; mirror CONFIRM bypass disabled
  under profit-only unless net > 0; probes use effective min net when profit-only.
- `tests/test_auditor.py`, `tests/test_profit_only_mode.py` — coverage.
- `.env` — profit-only YOLO profile (not committed); `.env.example` documents flags.

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_auditor.py tests/test_profit_only_mode.py -q
.\scripts\start_tradebot.ps1
```

## Notes
- Session PnL (wallet MTM) vs live fill net PnL measure different books — both kept,
  now labeled.
- Strategy rows sum to paper **gross** PnL (~$21.8k), not paper net (~$17.5k).
