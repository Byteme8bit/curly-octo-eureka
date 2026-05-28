# Discord style guide

How the bot talks in Discord. The goal: information density, low noise, scannable, consistent.

## Message types

| Type | When | Method | Pinned? |
|------|------|--------|---------|
| Plain status | Routine heartbeats, ticks | `post_plain` | no |
| Important | Trade events, mode changes, milestones | `post_important(pin=True)` | yes |
| Error | Exceptions in bot or watchdog | `post_error` | only if same key 3×+ in 30 min |
| Reply | Response to slash-ish commands | `send_reply` | no |

## Layout

Use Markdown sparingly:

```
**Trade executed**
ETH → ADA  (cross_momentum)
size 0.30  edge +0.7%  net +0.5%
fee $0.42  PnL +$1.18

[15s ago at 11:42:03 PDT]
```

Rules:

- One topic per message.
- Headline in bold on its own line.
- Body is plain text. Avoid emoji unless the operator requests them.
- Closing line: relative time + Pacific timestamp in brackets.
- Hard wrap is unnecessary — Discord wraps for you.

## Colors (when embeds are added)

Pull from `bot/ui_tokens.DISCORD`. Map message types to tokens:

| Message | Embed color |
|---------|-------------|
| Trade executed | `DISCORD.TRADE_EXECUTED` |
| Buy | `DISCORD.BUY` |
| Sell | `DISCORD.SELL` |
| Status — healthy | `DISCORD.SUCCESS` |
| Status — adaptive | `DISCORD.ADAPTIVE_MODE` |
| Status — hibernating | `DISCORD.HIBERNATING` |
| Status — circuit breaker | `DISCORD.CIRCUIT_BREAKER` |
| Strategy switch | `DISCORD.STRATEGY_SWITCH` |
| Heartbeat | `DISCORD.HEARTBEAT` |
| Milestone | `DISCORD.MILESTONE` |
| Error | `DISCORD.ERROR` |
| Warning | `DISCORD.WARNING` |
| Generic info | `DISCORD.INFO` |

## Pinning rules

Pinning is for messages the operator wants to find later. Pin sparingly.

| Always pin | Sometimes pin | Never pin |
|------------|---------------|-----------|
| Startup announcement | Trade with PnL > $5 | Heartbeats |
| Circuit breaker engaged | Strategy switch (governor) | Routine ticks |
| Hibernate / resume events | Repeated error (3+ in 30 min) | Holding-pattern updates |

The bot must clean up its own pins on next startup via `PinTracker`.

## Time references

- **Absolute:** Pacific (US/Pacific). Always include offset (`PDT` / `PST`).
- **Relative:** Discord auto-relativizes — just include `[abs]` and Discord users see "5 minutes ago".

## Command listener

Commands are namespaced by bot so it's always clear which bot is being
addressed. The general shape is `<BotName> -<action>` (case-insensitive,
dash optional, optional leading `!`, bot mentions stripped).

```
TradeBot -start       → resume trading ticks
TradeBot -stop        → pause trading
TradeBot -resume      → exit circuit-breaker re-evaluation
TradeBot -reset       → reset paper balances; clears Discord chat
TradeBot -portfolio   → current holdings and value
TradeBot -planned     → actions the bot is considering
TradeBot -strategy    → active strategy plugins
TradeBot -help        → TradeBot help only

WatchDog -status      → health score and risk assessment
WatchDog -pause       → watchdog pauses trade bot
WatchDog -clearchat   → bulk-delete recent messages (skips pinned)
WatchDog -help        → WatchDog help only

help                  → full help (all bots)
whoami                → return the sender's Discord user ID
```

Accepted bot prefixes: `TradeBot` / `tradebot` / `TB` and
`WatchDog` / `watchdog` / `WD`. Both `WatchDog -pause` and `WatchDog pause`
work — the leading dash is optional for forgiving UX.

Legacy single-word commands (`start`, `reset`, `portfolio`, etc.) still work
for one release as silent fallbacks, but the chat-log records a one-time
deprecation event per form pointing the user at the new prefixed name. The
help text only documents the new form.

`WatchDog -clearchat` (owner-only, like the other owner commands) bulk-deletes
recent channel messages via `POST /channels/{id}/messages/bulk-delete`,
preserving pinned messages and falling back to single `DELETE` for messages
older than 14 days (Discord rejects them from the bulk endpoint). The same
clear runs automatically at the end of `TradeBot -reset` so the post-reset
channel is clean. Requires the `MANAGE_MESSAGES` permission on the bot.

Reject any command from non-owner IDs silently — never reply. The exception
is `whoami`, which always replies so the operator can self-onboard.

## Logging

Everything that goes out (or comes in) is mirrored to `logs/discord_chat.log`. Gitignored (`logs/discord_chat*.log`). Format:

```
2026-05-25T18:42:03-07:00  [out|imp]  Trade executed | ETH → ADA ...
2026-05-25T18:42:09-07:00  [in|cmd]   <owner_id>  !status
```

## Don't

- Don't post the same message twice. Use `should_alert_error` deduplication.
- Don't post during shutdown after `discord.stop()`.
- Don't include API secrets or full webhook URLs in any message.
- Don't use Discord mentions (`@`) for routine events. Reserve for critical alerts the operator opted into.
