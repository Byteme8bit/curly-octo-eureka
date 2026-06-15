# 056 — Confidence-gated live mirror

**Requested:** 2026-06-15
**Status:** awaiting verification — pytest pending

## Request

After merging PR #53 (watchdog live gain alerts fix), mirror paper trades to
Kraken when the bot is confident — not fake PnL, but real execution when
live_tag is CONFIRM. DENY skips; UNCERTAIN configurable.

## Actions taken

- `bot/live_mirror.py` — verdict gating + skip log (`logs/live_mirror_skips.log`)
- `bot/verifier/live_tag.py` — export `is_multi_hop_trade`
- `bot/engine.py` — confidence gate in `_mirror_intent_to_live`; CONFIRM bypasses
  preflight block; Discord note on mirrored live fills; critical DENY alerts only
- `config.py` — `LIVE_MIRROR_MIN_CONFIDENCE`, `LIVE_MIRROR_UNCERTAIN`,
  `LIVE_MIRROR_SKIP_LOG_FILE`
- `.env.example`, `docs/live-trading.md` — document new knobs
- `tests/test_live_mirror.py`, `tests/test_live_mirror_confidence.py`

## Config (user `.env`, not committed)

```env
LIVE_MIRROR_MIN_CONFIDENCE=confirm
LIVE_STRICT_PROFIT=0
```

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_live_mirror.py tests\test_live_mirror_confidence.py -v
```

Restart TradeBot after merge:

```powershell
.\scripts\start_tradebot.ps1
```

## Notes

- Paper trades that skip live mirror are quiet (file log only) unless DENY is
  critical (pair missing, price mismatch vs Kraken ticker).
- Live mirror Discord posts include the live-viability tag from paper trade.
