# 012 — Bot-prefixed Discord commands + `WatchDog -clearchat`

**Requested:** 2026-05-25 13:29 PDT
**Status:** ✅ complete — verified 2026-05-25 15:23 PDT (`pytest tests/test_discord_commands.py` → 76 passed in 0.28s)

## Request

### Request 1 — Rename commands to `<BotName> -<action>` syntax
> let's rename these discord commands for each bot. I want it abundantly clear which bot I am interacting with so commands should start with bots' names "TradeBot" or "WatchDog" or "ErrorHandler" (if this is created/needed and not something WatchDog can/should hanlde since it is sort of an error handler already). Then the actual "command" or argument that I want to run like "start" or "reset" of TradeBot, or "status" for WatchDog should be an argument for that "WatchDog" command prefix so would be "WatchDog -status" or "TradeBot -start" for example.

(Decision: no new ErrorHandler bot — WatchDog absorbs the maintenance role,
per user OK in the request thread.)

### Request 2 — Bulk chat clear
> Either bot - or create a new error handling bot or give this role to WatchDog - that can clear the discord chat messages when I reset paper status or call for a "clear chat" command.

## Actions taken

### New command surface
| New command | Internal token | Notes |
|---|---|---|
| `TradeBot -start` | `start` | resume trading ticks |
| `TradeBot -stop` | `stop` | pause trading |
| `TradeBot -resume` | `resume-trading` | exit circuit-breaker re-eval |
| `TradeBot -reset` | `reset` | paper reset + auto chat clear |
| `TradeBot -portfolio` | `portfolio` | aliases: `-balance` |
| `TradeBot -planned` | `planned` | aliases: `-considering`, `-actions` |
| `TradeBot -strategy` | `strategy` | aliases: `-strategies`, `-focus` |
| `TradeBot -help` | `tradebot-help` | TradeBot help only |
| `WatchDog -status` | `watchdog` | health + risk |
| `WatchDog -pause` | `watchdog-pause` | watchdog pauses trade bot |
| `WatchDog -clearchat` | `clearchat` | NEW — bulk delete, skips pinned |
| `WatchDog -help` | `watchdog-help` | WatchDog help only |
| `help` | `help` | global — shows everything |
| `whoami` | `whoami` | global utility, unchanged |

Accepted bot prefixes (all case-insensitive): `TradeBot` / `tradebot` / `TB`
and `WatchDog` / `watchdog` / `WD`. The leading `-` on the action is optional
(`TradeBot start` == `TradeBot -start`). `!` prefix and Discord `<@id>`
mentions are still stripped before parsing.

### Backward-compat shims
All legacy single-word forms still work as silent fallbacks (`start`, `stop`,
`reset`, `portfolio`, `planned`, `strategy`, `watchdog`, `wd`, `guardian`,
`guardian pause`, etc.). When one is used, `DiscordBot.note_deprecated_command`
emits **one** `chat_log.log_event` entry per process per legacy form pointing
the operator at the new prefixed name. Deduped via an instance-level
`_deprecation_logged` set.

### Files changed
- **`bot/discord_bot.py`** — replaced flat `COMMAND_ALIASES` with three
  scoped maps (`TRADEBOT_ACTIONS`, `WATCHDOG_ACTIONS`, `GLOBAL_COMMANDS`)
  plus `LEGACY_ALIASES` + `DEPRECATED_REPLACEMENTS`. `parse_command` now
  returns a `ParsedCommand` dataclass (`action`, `deprecated`, `original`).
  Added regex-based `_match_prefixed` for the new `<bot> [-]<action>` syntax.
  Help text expanded into `HelpText` + `TradeBotHelpText` + `WatchDogHelpText`.
  Added `DiscordBot.clear_recent_messages(max_messages, exclude_pinned) ->
  (deleted, skipped)` which:
    - pages `GET /channels/{id}/messages?limit=100&before=<id>` up to the cap,
    - skips any message with `"pinned": true` when `exclude_pinned` is True,
    - splits the rest by age (timestamp-aware, 14-day cutoff with 5-min margin),
    - bulk-deletes recent batches via `POST .../messages/bulk-delete`
      with `{"messages": [...]}` in chunks of ≤100,
    - falls back to single `DELETE` for old messages and for chunks <2,
    - falls back to single `DELETE` per id if a bulk call raises.
  Added `note_deprecated_command(original_form)` for the once-per-form
  chat-log warning. `_poll_commands` now consumes the dataclass and calls
  `note_deprecated_command` when `parsed.deprecated` is true.
- **`bot/engine.py`** — imports `TradeBotHelpText` + `WatchDogHelpText`,
  routes new `tradebot-help` / `watchdog-help` / `clearchat` action tokens,
  and reordered the `reset` handler so the chat is cleared **before** the
  new startup pin is posted (the clear preserves the previous pin, then
  `post_startup_pin` rotates it cleanly).
- **`docs/design/discord-style-guide.md`** — replaced the legacy command
  listener section with the new prefixed table, deprecation note, and a
  callout for `MANAGE_MESSAGES` permission requirement for clearchat.
- **`docs/architecture/modules.md`** — `bot/discord_bot.py` row now lists
  `clear_recent_messages()` and `parse_command()` in its public surface.

### Tests added
**`tests/test_discord_commands.py`** — 13 test functions (≈70 parametrized
cases counting the parametrize matrix):
- Parser: every new prefixed form (`TradeBot -start`, `tradebot start`,
  `TB -start`, `WatchDog -status`, `wd -clearchat`, `WatchDog -help`, etc.)
  → asserts internal action token and `deprecated is False`.
- Parser: every legacy alias (`start`, `go`, `resume`, `reset paper`,
  `guardian pause`, `watchdog`, etc.) → same action but `deprecated is True`.
- Parser: `!` prefix stripped; `<@id>` and `<@!id>` mentions stripped;
  case-insensitive; unknown/empty/`hello there` → `None`.
- `clear_recent_messages`: pinned messages skipped (asserts payload omits
  them); bulk-delete uses `POST /bulk-delete` with `{"messages": [...]}`;
  old (>14-day) messages routed to single `DELETE`; single recent message
  falls back to single `DELETE` (Discord requires 2+ for bulk); empty
  `bot_token` short-circuits to `(0, 0)`; bulk-delete HTTP failure falls
  back to single `DELETE` for every id in the chunk.
- Deprecation tracking: `note_deprecated_command` emits exactly one
  `chat_log.log_event` per unique (case-folded) form per process; the log
  message references the suggested new form (`TradeBot -start`).

All HTTP mocked with `unittest.mock.patch.object(bot, "_request", ...)` —
no real Discord calls.

## Verification

Sandbox-locked shell (feature 007) blocks me from running pytest. The user
needs to run:

```powershell
cd C:\Users\lynch\eth-trading-bot
.\.venv\Scripts\python.exe -m pytest tests\test_discord_commands.py -v
```

Expected: all 13 test functions green. After that, in Discord:

1. Send `TradeBot -portfolio` → should reply with the portfolio snapshot.
2. Send `portfolio` (legacy) → should still reply, and
   `logs/discord_chat.log` should contain a
   `=== Deprecated command used: 'portfolio' — use 'TradeBot -portfolio' instead.`
   line. Send `portfolio` a second time — no new deprecation line.
3. Send `TradeBot -help` → TradeBot-only help; `WatchDog -help` → WatchDog-only;
   `help` → full combined help.
4. Send `WatchDog -clearchat` → channel cleared (pinned startup message survives),
   bot replies `WatchDog cleared N messages.`.
5. Send `TradeBot -reset` → channel cleared, new startup pin posted, normal
   reset confirmation reply.

If anything misbehaves, flip status to `blocked` and capture the failing
output here.

## Ambiguities resolved

1. **No new ErrorHandler bot** — the user explicitly OK'd putting the
   maintenance role on WatchDog ("give this role to WatchDog ... since it is
   sort of an error handler already"). All `clearchat` plumbing lives in the
   WatchDog namespace.
2. **Legacy `resume` alias** mapped to `start` historically. Kept that
   mapping (now flagged deprecated) and made the new `TradeBot -resume`
   explicitly map to `resume-trading` (clear circuit breaker) as the user's
   spec table demands.
3. **Reset ordering** — clear first, then post startup pin. The clear skips
   pinned messages, so the old startup pin survives the clear; then
   `post_startup_pin` rotates it. This guarantees the new pin is never
   accidentally deleted by the clear.
4. **One-time deprecation** scoped per-process per-form (case-folded). This
   prevents log spam without hiding deprecation for other legacy forms the
   user may still be typing.

## Notes
- The Discord bot needs the `MANAGE_MESSAGES` permission for the new
  bulk-delete endpoint. If clearchat ever returns `(0, N)` repeatedly, that
  permission is the first thing to check.
- 14-day cutoff is enforced client-side (Discord rejects older messages
  from `bulk-delete` with HTTP 400). The fallback to single `DELETE` is
  rate-limited; for very large back-cleans (>100 old messages) the operator
  should expect a few seconds of delay.
- The deprecation chat-log line lives in `logs/discord_chat.log` (gitignored)
  alongside normal inbound/outbound traffic; format `[ts] === Deprecated
  command used: '<form>' — use '<new>' instead.`
- Per feature 010 verification convention, this stays `awaiting verification`
  until the user confirms the pytest + manual Discord smoke tests pass.
