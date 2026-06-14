# 053 — Auditor live PnL labeling and prop docs

**Requested:** 2026-06-14
**Status:** awaiting verification — pytest pending

## Request

User reported auditor scheduled report headline **Net PnL $6,555.67** while
`LIVE_ENABLED=1` — believed to be paper PnL, not real Kraken PnL. Also:
confusing forecast numbers, goal milestones ($10k/$100k/$1M) should track live
portfolio, and whether Kraken Trade Prop can be used.

## Actions taken

- `bot/auditor/context.py` — live snapshot + goal view helpers (read-only)
- `bot/auditor/report.py` — dual **Paper PnL** / **Live Kraken PnL** sections,
  forecast plain-English explainer, portfolio goals block
- `bot/auditor_service.py` — load live state, pass context to report/Discord
- `bot/engine.py` — wire `live_broker_provider` into auditor
- `dashboard/parsers/auditor.py` — parse paper vs live headline fields
- `docs/kraken-prop.md` — Trade Prop not supported; spot only
- `docs/live-trading.md` — link to prop doc
- `config.py` / `.env.example` — `PROP_ENABLED` stub (no-op)
- `tests/test_auditor.py` — labeling + live snapshot tests

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_auditor.py -v -k "live_mode or live_audit"
.\.venv\Scripts\python.exe -m pytest tests\test_auditor.py -v
```

Restart bot and run `Auditor -review` with `LIVE_ENABLED=1` — report should
show paper $6.5k+ separate from live ~$1.6k spot portfolio.

## Notes

- Forecasts remain based on **paper trade history** (simulation pace); labeled
  explicitly when live is armed.
- Goal milestones use live spot portfolio when `.live_state.json` has balances.
- Kraken Trade Prop ($5k eval) is a separate Kraken Pro account — not integrated.
