# 035 — Document Discord command set in README

**Requested:** BACKLOG "Soon" — `DISCORD_COMMANDS.txt` exists but is not linked
from the README.
**Status:** complete

## Problem

`DISCORD_COMMANDS.txt` is the authoritative Discord command reference (231 lines)
but was not discoverable from `README.md`. New users had to know to look for it.

## Actions taken

### `README.md`

Added a "Discord commands" section above the existing "Documentation" section
with:
- A direct link to [`DISCORD_COMMANDS.txt`](DISCORD_COMMANDS.txt).
- A quick-reference table of the 10 most-used commands across all three bot
  personas (`TradeBot`, `WatchDog`, `Auditor`).

## Notes
- No code changes — documentation only.
- `DISCORD_COMMANDS.txt` itself is unchanged.
