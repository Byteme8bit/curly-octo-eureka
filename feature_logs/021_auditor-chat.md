# 021 — Auditor conversational chat (Gemini-backed Q&A)

**Requested:** 2026-05-27
**Status:** awaiting verification — pytest pending, live Discord smoke test pending

## Request
> I want to be able to ask Auditor questions about TradeBot and have a conversation with it. How do we get this going?

Followups via the design questionnaire:
- **Backend:** Gemini (user has a Google subscription).
- **Style:** both single-turn (`-ask`) and multi-turn (`-chat`).
- **Powers:** read-only Q&A about TradeBot actions and WatchDog reports. Goal: offload Cursor token usage; do not change the existing propose/confirm flow.

## Important setup note for the user

The consumer **Gemini Pro** subscription at gemini.google.com is *separate* from API access. To use chat:

1. Visit [aistudio.google.com](https://aistudio.google.com).
2. Click "Get API key" → "Create API key in new project".
3. Copy the key into `.env` as `GEMINI_API_KEY=...`.
4. Set `AUDITOR_CHAT_ENABLED=1`, restart `main.py`.

Free tier limits at the time of writing (always check Google's docs for current numbers):
- gemini-2.0-flash: ~15 requests/minute, ~1500/day, 1M tokens/day.
- gemini-2.5-pro: more restrictive on free tier (~5 RPM).

For a personal bot the free tier is plenty.

## Design

### Module layout
```
bot/auditor/chat/
  __init__.py        — public API re-exports
  tools.py           — read-only tool registry + factory
  backends.py        — LLMBackend ABC, GeminiBackend, NullBackend
  service.py         — ChatService (ask/chat/clear/history_summary)
```

### Tools the LLM can call (all read-only)
| Tool | Returns |
|---|---|
| `get_portfolio_snapshot` | Balances, peak USD, drawdown summary line |
| `get_recent_trades(limit, asset?, strategy?)` | Newest-first trade list with PnL/fees |
| `get_strategy_performance` | Per-strategy win/loss/PnL aggregates |
| `get_active_overrides` | Current `runtime_overrides.json` knob values |
| `get_pending_proposals` | Auditor proposals waiting for `-confirm` |
| `get_last_audit_summary(max_chars?)` | Most recent audit markdown report |
| `get_watchdog_health` | Last watchdog health snapshot |
| `get_recent_errors(limit?, source?)` | Recent bot/watchdog errors |
| `get_recent_news(limit?, ticker?)` | Free RSS/CoinGecko headlines |
| `get_bot_settings` | Effective settings AFTER runtime overrides |
| `get_market_prices` | Cached USD marks for watched assets |

Tools never raise — failures return `{"error": "..."}` so the LLM can describe the failure naturally.

### Backend abstraction (`bot/auditor/chat/backends.py`)
- `LLMBackend` Protocol: `complete(messages, tools, temperature, max_output_tokens) -> LLMReply`.
- `GeminiBackend` — lazy imports `google-genai` only on first call so a missing SDK never blocks startup. Translates our normalised `LLMMessage` shape into Gemini `Content`/`Part` objects and adapts `FunctionDeclaration` for tool-calling.
- `NullBackend` — returns a canned "chat disabled" string. Used by tests + as a safe fallback when configuration is incomplete.

### ChatService (`bot/auditor/chat/service.py`)
- `ask(question)`: single-turn, no memory.
- `chat(session_id, message)`: multi-turn, history keyed by `session_id` (we pass the Discord author id, so each authorised user has their own private thread).
- Strict system prompt explicitly forbids the LLM from promising actions and reminds it the bot is read-only and paper-only.
- Internal loop runs `complete` → execute returned tool calls → feed results back → repeat. Hard-capped by `AUDITOR_CHAT_TOOL_ITERATIONS` (default 4) so a confused LLM can't loop forever.
- Per-channel `threading.Lock` so concurrent Discord messages from the same user can't interleave.

### Discord surface
Added to `AUDITOR_ACTIONS`:
- `ask` → `auditor-ask`
- `chat` → `auditor-chat`
- `clearchat` / `clear-chat` → `auditor-clearchat`
- `chatstatus` / `chat-status` → `auditor-chatstatus`

`ask` and `chat` are in `_AUDITOR_ACTIONS_WITH_ARGS` so the parser packs the trailing text into the action string.

The engine's `_handle_discord_command` now passes `user_id` into `_handle_auditor_command`, which routes chat actions to `auditor.ask/chat/clear_chat/chat_status`.

### Config (all opt-in, default OFF)
```
AUDITOR_CHAT_ENABLED=0
AUDITOR_CHAT_BACKEND=gemini       # or "null" for tests
AUDITOR_CHAT_MODEL=gemini-2.0-flash
GEMINI_API_KEY=                   # from aistudio.google.com
AUDITOR_CHAT_MAX_TURNS=10
AUDITOR_CHAT_MAX_TOKENS=1500
AUDITOR_CHAT_TEMPERATURE=0.3
AUDITOR_CHAT_TOOL_ITERATIONS=4
```

### Tests (`tests/test_auditor_chat.py`)
20+ tests covering:
- Tool registry shape and per-tool behavior (portfolio, trades filtering, strategy aggregates, overrides, audit summary, missing news client).
- Tool exception swallowing.
- `ChatService.ask` single-turn happy path.
- Empty question returns help text.
- Tool-call → synthesis round trip.
- Tool-iteration cap.
- Multi-turn memory retention + truncation to `max_turns`.
- `clear` wipes per-session history.
- `history_summary` reports per-session turn counts.
- Backend error returns graceful `result.error=True`.
- AuditorService disabled-chat path returns a setup hint.
- AuditorService with null backend returns the canned reply.
- `chat_status` reports backend, model, sessions.

No tests touch the real Gemini SDK or hit the network.

## Files changed

- **Added** `bot/auditor/chat/__init__.py`, `tools.py`, `backends.py`, `service.py`.
- **Added** `tests/test_auditor_chat.py`.
- **Added** `feature_logs/021_auditor-chat.md`.
- **Modified** `bot/auditor/config.py` — 8 new chat fields with defaults.
- **Modified** `config.py` + `.env.example` — new env vars + GEMINI_API_KEY.
- **Modified** `bot/auditor_service.py` — `ask`, `chat`, `clear_chat`, `chat_status`, `status()` updated, lazy `_get_chat_service` builder.
- **Modified** `bot/engine.py` — `_handle_discord_command` passes `user_id` through; `_handle_auditor_command` routes new tokens.
- **Modified** `bot/discord_bot.py` — extended `AUDITOR_ACTIONS`, `_AUDITOR_ACTIONS_WITH_ARGS`, and `AuditorHelpText`.
- **Modified** `requirements.txt` — added `google-genai>=0.3.0`.

## Try it after setup

```
Auditor -chatstatus
Auditor -ask How are we doing today?
Auditor -ask What was our worst trade in the last 24h?
Auditor -chat Walk me through the most recent audit and why it suggested what it did.
Auditor -chat Has there been any negative ETH news?
Auditor -clearchat
```

## Risks / open questions

- **Token spend.** With the free-tier Gemini key and the tool-iteration cap of 4, a typical question costs ~3-10k tokens. Free tier covers thousands of questions/day. If the user upgrades the key to paid, watch the bill — there's no per-session cost cap yet (followup).
- **Tool payload size.** Tools cap their returns (50 trades, 25 errors, 15 headlines) but raw audit markdown can be large; `get_last_audit_summary` truncates at 4000 chars by default.
- **Session keying.** Today: per Discord user. If the user wants per-channel instead, swap `user_id` for the channel id in `_handle_discord_command`.
- **No streaming.** The full reply is generated before posting to Discord. Fine for now (Gemini Flash is quick) but a follow-up could stream chunks.
- **No conversation persistence across restarts.** Chat history lives only in memory; `os.execv` restart wipes it. Add a JSON store later if desired.
- **No rate limiting in the bot.** Discord users could spam questions; Gemini's free tier will rate-limit before any real harm, but a per-user N-questions-per-minute cap would be a polite follow-up.
