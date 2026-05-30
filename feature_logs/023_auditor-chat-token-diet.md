# 023 — Slash Gemini token usage (Auditor chat token diet)

**Requested:** 2026-05-30
**Status:** awaiting verification — pytest pending, live Discord smoke test pending

> _Backfilled 2026-05-30 from `VersionHistory/CHANGELOG.md` + saved patches after
> a chat-context loss. The code shipped at 02:32 PDT; this log reconstructs the
> "why" from the recorded diffs._

## Request
> The Auditor chat works now, but it burns through the Gemini free-tier quota
> fast. Cut the token usage without losing usefulness, and make rate-limit
> errors readable instead of dumping raw JSON into Discord.

## What changed and why

### 1. Lower the per-question budget (`bot/auditor/chat/service.py`, `config.py`, `bot/auditor/config.py`, `.env.example`)
Each tool round-trip resends the *entire* conversation to Gemini, so the biggest
levers are how many round-trips we allow and how big each tool result is.

| Knob | Old | New | Why |
|---|---|---|---|
| `chat_max_turns` | 10 | 6 | Shorter rolling history per channel |
| `chat_tool_iterations` | 4 | 2 | Most answers need ≤ 2 tool waves; each wave is a full resend |
| `chat_max_tokens` | 1500 | 1000 | Tighter reply cap |
| `chat_tool_result_max_chars` | 8000 (hard-coded slice) | 2000 (configurable) | Tool payloads dominate token cost |

All are env-overridable (`AUDITOR_CHAT_*`).

### 2. Per-turn tool-result cache (`service.py`)
A confused LLM would call e.g. `get_portfolio_snapshot` several times in one
turn. We now cache by `(tool_name, stable-json-args)` for the duration of a
single chat turn — identical calls execute once and reuse the same (already
truncated) JSON blob. New helper `_stable_args_key` produces a sort-stable key.

### 3. Truncate tool payloads before they hit the model (`service.py`)
Tool JSON is now truncated to `tool_result_max_chars` *before* being appended to
the message list (with a `..."(truncated)"` marker), instead of relying on a
downstream `[:8000]` slice. Less context bloat on every subsequent iteration.

### 4. Tighter system prompt (`service.py`)
Rewrote the instructions to push efficiency: plan tools before calling, batch
tool calls in one turn, never repeat an identical call, answer general/greeting
questions with **no** tool calls, and keep replies to ≤ 6 short sentences.

### 5. Better default model (`bot/auditor/config.py`, `config.py`, `.env.example`)
Default `chat_model` changed from `gemini-2.0-flash` to **`gemini-2.5-flash-lite`**
— best free-tier headroom of the flash family (~15 RPM / 1000 RPD / 250K TPM
vs 2.0-flash's 200 RPD).

### 6. Graceful Gemini error handling + one auto-retry (`bot/auditor/chat/backends.py`)
New `_classify_gemini_error` translates raw SDK exceptions into friendly,
single-line Discord messages categorised as `rate_limit` / `auth` /
`bad_request` / `server` / `network` / `other`. Helpers:
- `_extract_status_code` — best-effort HTTP status across SDK exception shapes.
- `_extract_retry_after_seconds` / `_parse_duration_string` — pull Gemini's
  suggested `retryDelay` (e.g. `"17s"`) out of attributes or the JSON-in-string blob.
- `_first_line` — collapse verbose error dumps to one informative line.

On a 429 whose suggested delay is ≤ `AUTO_RETRY_MAX_SECONDS` (20s), the backend
sleeps and retries **once**; longer delays surface immediately so Discord never
appears to hang. Rate-limit replies suggest switching models and link the quota docs.

## Incidental change
`config.py` default `MIN_ETH_RESERVE` bumped `0.25` → `0.5` (picked up in the
same snapshot batch).

## Files changed

- **Modified** `bot/auditor/chat/service.py` — caching, truncation, lower caps, new system prompt (+45 / -9).
- **Modified** `bot/auditor/chat/backends.py` — error classification + single auto-retry (+143 / -5).
- **Modified** `bot/auditor/config.py` — 9 chat config fields with tuned defaults (+19 / -0).
- **Modified** `bot/auditor_service.py` — lazy chat wiring (`ask`/`chat`/`clear_chat`/`chat_status`, `_build_chat_service`, `_get_chat_service`, news-client reuse) (+151 / -0).
- **Modified** `bot/engine.py` — route `auditor-ask/chat/clearchat/chatstatus`, thread `user_id`, pass chat config into AuditorService (+28 / -3).
- **Modified** `config.py` — new `auditor_chat_*` settings + env parsing; `MIN_ETH_RESERVE` default 0.25→0.5 (+19 / -1).
- **Modified** `.env.example` — documented new `AUDITOR_CHAT_*` vars (+39 / -1).
- **Modified** `tests/test_auditor_chat.py` — coverage for caching, truncation, error classification, retry (+210 / -0).

## Version history

All snapshotted under Request 023 (2026-05-30 02:32 PDT):
`bot/auditor/chat/service.py` r001 · `bot/auditor/chat/backends.py` r002 ·
`bot/auditor/config.py` r002 · `bot/auditor_service.py` r002 · `bot/engine.py` r003 ·
`config.py` r002 · `.env.example` r002 · `tests/test_auditor_chat.py` r002.

## Verification (pending — sandbox-locked shell)

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_auditor_chat.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

Live smoke test after setting `GEMINI_API_KEY` + `AUDITOR_CHAT_ENABLED=1`:

```
Auditor -chatstatus
Auditor -ask How are we doing today?
Auditor -chat Walk me through the most recent audit.
Auditor -clearchat
```

## Risks / open questions

- **No hard per-session token/cost cap yet** — the caps above reduce spend but
  don't enforce a ceiling. A per-user N-questions-per-minute limit is a follow-up.
- **Model availability** — if `gemini-2.5-flash-lite` is unavailable on a given
  key, set `AUDITOR_CHAT_MODEL` to another free model and restart.
- **Truncation can hide data** — a 2000-char tool cap may clip large trade/audit
  payloads; bump `AUDITOR_CHAT_TOOL_RESULT_MAX_CHARS` if answers feel incomplete.
