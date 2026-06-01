# 022 — Fix NameError in GeminiBackend tool declarations

**Requested:** 2026-05-30
**Status:** awaiting verification — pytest pending

> _Backfilled 2026-05-30 from `VersionHistory/CHANGELOG.md` + saved patches after
> a chat-context loss. The code change itself shipped at 02:17 PDT; this log
> reconstructs the "why" from the recorded diff._

## Request
> The Auditor chat (from request 021) crashed when the LLM tried to use tools —
> a `NameError` blew up while building the Gemini tool declarations.

## Root cause

In `GeminiBackend._complete`, the tool list was built with a comprehension that
referenced the loop variable `t` outside of any loop:

```python
config_kwargs["tools"] = [_tool_to_gemini_declaration(t, types)]
```

`t` was never defined in that scope, so the moment any chat request carried
tools, Python raised `NameError: name 't' is not defined` before the request
ever reached Gemini. Single-turn answers that happened to need no tools would
sneak by; anything that needed live bot state crashed.

## Fix

One-line correction to actually iterate over the registered tools:

```python
config_kwargs["tools"] = [_tool_to_gemini_declaration(t, types) for t in tools]
```

## Files changed

- **Modified** `bot/auditor/chat/backends.py` — fix the tools comprehension (+1 / -1).
- **Modified** `tests/test_auditor_chat.py` — added regression coverage so a
  tools-carrying request exercises the declaration builder (+89 / -0).

## Version history

- `bot/auditor/chat/backends.py` — r001 (Request 022)
- `tests/test_auditor_chat.py` — r001 (Request 022)

## Verification (pending — sandbox-locked shell)

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_auditor_chat.py -q
```

## Notes

- This fix is a prerequisite for the token-usage work in request 023; without
  it, every tool-using chat turn errored out before any optimisation mattered.
