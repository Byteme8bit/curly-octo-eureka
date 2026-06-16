# 065 — Paper anchor to live in mirror mode

**Requested:** 2026-06-15
**Status:** awaiting verification — pytest pending

## Request
Paper portfolio ~$12k vs live Kraken ~$1.6k in `LIVE_MIRROR_PAPER` mode. Anchor paper to live on session start and on demand so mirror-mode testing is meaningful.

## Root cause
Paper `.paper_state.json` accumulated months of triangular arb / multi-asset sim trades (DOT, UNI, AAVE, etc.) while live mirror executed only a gated subset (~13 trades). No sync between paper book and Kraken spot.

## Actions taken
- `bot/paper_anchor.py` — copy live balances into paper, reset paper risk baselines
- `config.py` — `PAPER_ANCHOR_TO_LIVE` (default `1` when `LIVE_MIRROR_PAPER=1`)
- `bot/engine.py` — anchor on `run()` startup + `TradeBot -reset` in mirror mode
- `scripts/anchor_paper_to_live.py` — one-shot re-anchor without restart
- `bot/report.py` — portfolio labels explain anchoring
- `docs/live-trading.md` — short paper-anchor section
- `tests/test_paper_anchor.py`, `tests/test_portfolio_command.py`

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_paper_anchor.py tests\test_portfolio_command.py -q
.\.venv\Scripts\python.exe scripts\anchor_paper_to_live.py
# Restart TradeBot; TradeBot -portfolio should show live ~ paper at startup
```
