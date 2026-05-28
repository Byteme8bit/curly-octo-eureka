# 009 — Feature request log + Discord chat log

**Requested:** 2026-05-25 11:41 PDT
**Status:** complete

## Request
> Let's start logging all of my feature requests into a separate log file. Each feature request should have it's own log file where you log what I requested, then the actions taken for that specific request.
>
> Secondly, I'd like to log the Discord chat to separate a local file.

## Actions taken

### Feature request log
- Created `feature_logs/` directory with `README.md` describing the format
- Backfilled all eight prior requests from this session (001–008)
- Going forward, the agent will add a new `NNN_short-name.md` for each new request and update its "Actions taken" section as work progresses

### Discord chat log
- Added `bot/discord_chat_log.py` with a thread-safe append-only logger
- `bot/discord_bot.py` wired to log:
  - Inbound: every command/message received by the listener (timestamp, user, text)
  - Outbound: every message the bot posts (timestamp, content snippet, pin/normal)
- Log path: `logs/discord_chat.log` (gitignored)

## New config
| Setting | Default | What it does |
|---|---|---|
| `DISCORD_CHAT_LOG_ENABLED` | `1` | Toggle local chat logging |
| `DISCORD_CHAT_LOG_FILE` | `logs/discord_chat.log` | Override log path |

## Notes
- Discord chat log is gitignored alongside other runtime files.
- Feature request files are committed to git so the project history is reviewable.
