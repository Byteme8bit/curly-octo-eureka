# 034 — Pre-flight reject messages in basis points + README Discord command doc

**Requested:** 2026-06-01 (backlog item "Soon")
**Status:** complete

## Request

1. **Pre-flight reject messages** currently show raw decimals
   (`gross +0.0012 - fees 0.0040 - slippage 0.0005`).
   Show basis points (12bps - 40bps - 5bps) instead, which is easier to read.

2. **Document the full Discord command set in `README.md`.**
   We have `DISCORD_COMMANDS.txt` but it's not linked from the README.

## Actions taken

- **Modified** `bot/preflight.py`:
  - Added private helper `_bps(pct: float) -> str` that converts a fractional
    return (e.g. `0.0012`) to a human-readable basis-point string (`+12bps`).
  - Updated both the reject reason and the OK reason strings to use `_bps()`.
  - Example before: `net +0.0012 (gross +0.0025 - fees 0.0010 - slippage 0.0003) <= min 0.0060`
  - Example after:  `net +12bps (gross +25bps - fees 10bps - slippage 3bps) <= min 60bps`

- **Modified** `README.md`:
  - Added a new **Discord commands** section before the Documentation section.
  - Contains a prefix/purpose table, a quick-reference code block, and a link
    to `DISCORD_COMMANDS.txt` for the full reference.

## Verification

```
python3 -m pytest -v
```

282 tests pass.

## Notes

`_bps()` uses `round()` (not integer truncation) so 0.00125 → `+13bps` rather
than `+12bps`. The existing `test_preflight.py` suite is sparse; the log
string format change is visible in `bot.log` during paper runs.
