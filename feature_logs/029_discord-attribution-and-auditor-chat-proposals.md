# 029 — Discord per-source attribution + Auditor chat proposals

**Requested:** 2026-06-01 07:00 PDT
**Status:** awaiting verification - pytest pending

## Request
Two Discord/Auditor issues:

1. **Discord attribution** — every message (including WatchDog and Auditor
   messages) shows up in Discord as "TradeBot". Want WatchDog messages
   attributed to WatchDog and Auditor messages to the Auditor, using the
   webhook per-message `username` override where possible, and handling the
   bot-token limitation gracefully.
2. **Auditor can't make proposals from chat** — when asked via
   `Auditor -ask` / `-chat` to "audit … and make a proposal to improve
   strategy or code", it replies it cannot. The read-only Gemini chat has
   lookup tools but no way to create a proposal. Give it a tool/method that
   registers a concrete pending proposal into the SAME store confirmed with
   `Auditor -confirm <id>`, WITHOUT bypassing the propose→confirm flow or
   auto-applying anything.

## Actions taken

### Issue 1 — attribution (`bot/discord_bot.py`, `bot/engine.py`, `bot/auditor_service.py`)
- Added `DEFAULT_SOURCE = "TradeBot"` and a `webhook_username` base name on
  `DiscordConfig` (default `"TradeBot"`).
- Threaded a `source` argument through `post_status`, `post_plain`,
  `post_important`, `send_reply`, and the internal `_send_message`.
- **Webhook transport:** each post sets the per-message `username`
  (`TradeBot`, `TradeBot · WatchDog`, `TradeBot · Auditor`) and a matching
  `avatar`-free override — real per-message attribution.
- **Bot-token transport:** Discord does not allow per-message username
  overrides on bot-account messages, so for non-default sources we prepend a
  concise `**[WatchDog]** ` / `**[Auditor]** ` text label. Documented as the
  known bot-token limitation.
- `source_for_action()` maps a parsed command token to its owning subsystem
  so command replies (sent via bot token) are labelled correctly.
- `engine._watchdog_alert` now posts with `source="WatchDog"`; the auditor
  service summary + auto-apply notices post with `source="Auditor"`.

### Issue 2 — Auditor chat can create proposals
- `bot/auditor/proposer.py`: added public `build_proposal(...)` helper
  (validates knob ∈ `ALLOWED_KNOBS`, normalises severity) reused by the
  service.
- `bot/auditor_service.py`: added `create_proposal(...)` which builds a
  `ConfigProposal` and registers it into the SAME `AuditorState.pending_proposals`
  store (locked + persisted). It NEVER applies the change — only the existing
  `Auditor -confirm <id>` flow applies overrides.
- `bot/auditor/chat/tools.py`: new `create_proposal` tool (only registered
  when a `proposal_creator` callback is supplied) so the LLM can draft a
  concrete knob proposal.
- `bot/auditor/chat/service.py`: system prompt updated to permit creating a
  PENDING proposal (the single allowed side effect) while still forbidding
  auto-apply / code / strategy changes.

## Verification
Agent shell is sandbox-locked (cannot run pytest). User to run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

New tests:
- `tests/test_discord_commands.py` — webhook username override + bot-token
  text-prefix attribution + `source_for_action` mapping.
- `tests/test_auditor_chat.py` / `tests/test_auditor.py` — `create_proposal`
  tool + service method, and end-to-end list/confirm of a chat-created proposal.

## Notes
- **Bot-token limitation:** with `DISCORD_BOT_TOKEN` configured (the user's
  setup), status posts go via the bot token, which cannot rename per message;
  attribution there appears as a `**[WatchDog]**` / `**[Auditor]**` prefix.
  Webhook-only deployments get a true `username` override.
- Safety preserved: chat can only CREATE a pending proposal; apply still
  requires `Auditor -confirm <id>`; auto-apply guardrails untouched.
- Parent must merge the PR and restart the running bot for changes to load.
