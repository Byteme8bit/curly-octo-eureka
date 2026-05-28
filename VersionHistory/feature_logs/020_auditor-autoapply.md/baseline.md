# 020 — Auditor sleep-window auto-apply + self-restart

**Requested:** 2026-05-27
**Status:** awaiting verification (tests written, manual smoke test pending)

## Request
> If the auditor bot has a high confidence in its proposed changes and does not receive a response from me while I am sleeping say between 1am - 7am PST, I'd like to allow it to implement ONE proposed change while I am sleeping without any confirmation and be able to restart TradeBot on its own to apply the proposed changes.

User explicitly acknowledged this is "probably not advisable". The implementation therefore defaults to **OFF** and enforces multiple safety gates.

## Design

### Eligibility — ALL of these must be true for an auto-apply

1. `AUDITOR_AUTOAPPLY_ENABLED=1` (explicit opt-in).
2. Current Pacific hour is within `[AUDITOR_AUTOAPPLY_WINDOW_START_HOUR, AUDITOR_AUTOAPPLY_WINDOW_END_HOUR)`. Cross-midnight windows supported (e.g. 23–7).
3. The proposal's `severity` is at least `AUDITOR_AUTOAPPLY_MIN_SEVERITY` (default `high`). Only one proposer rule emits `high` today: forecast central tendency negative across all horizons.
4. The per-night counter for that night key is below `AUDITOR_AUTOAPPLY_MAX_PER_NIGHT` (default `1`).
5. The broker is healthy — no drawdown hibernation (`risk.state.paused_until`) and no active hibernate alert (`risk.state.hibernate_alert_sent`).

If any gate fails the proposal is left as a pending suggestion for `Auditor -confirm` exactly as before.

### Apply + restart sequence

1. `apply_proposal()` writes the chosen knob into `runtime_overrides.json` (same path as a manual `Auditor -confirm`).
2. The pending proposal is consumed; `AuditorState.mark_auto_apply(...)` records `last_auto_apply_at`, `_proposal_id`, `_knob`, `_value`, `_night_key`, and increments `auto_applies_this_night`.
3. A loud pinned Discord message is posted: knob, old → new, severity, rationale, applied-at timestamp, and a reminder of `Auditor -revert KNOB`.
4. If `AUDITOR_AUTOAPPLY_RESTART_ENABLED=1`, the auditor calls the engine's `request_restart()` callback. The engine flips `_restart_requested=True` and asks the runtime to shut down.
5. The main run loop exits, `shutdown()` stops watchdog/auditor/discord cleanly, then `_perform_self_restart()` sleeps 2 s (so Discord can flush its final messages) and calls `os.execv(sys.executable, [sys.executable, *sys.argv])`.
6. The replacement process loads `runtime_overrides.json` during `load_settings()`. Startup pin now includes a `⚙️ Auditor overrides active: ...` line so the user sees the new value on wake-up.

### Night key

`AuditorState.last_auto_apply_night_key` tracks which 24h block the cap applies to:

- Same-day window (1–7): night key = current date.
- Cross-midnight window (e.g. 23–7): night key = *yesterday's* date when the current hour is before `end_hour`, so the late-night and early-morning segments share one counter.

### Knobs that can be auto-applied

Strictly the existing `ALLOWED_KNOBS` whitelist — auto-apply does **not** expand the surface area:

- `MIN_TRADE_EDGE`
- `TRADE_SIZE_PCT`
- `MIN_NET_PROFIT_PCT`
- `IDLE_REEVAL_HOURS`
- `STRATEGY_EXPLORATION_RATIO`

Policy knobs (ETH reserve, alt cap, fees, circuit breaker, hibernation thresholds) remain off-limits in every path.

## Files changed

- `bot/auditor/config.py` — added six auto-apply fields (defaulted OFF).
- `bot/auditor/state.py` — added six audit-trail fields with JSON round-trip.
- `bot/auditor_service.py` — new `_maybe_auto_apply`, `_inside_sleep_window`, `_broker_is_healthy`, `_notify_auto_apply` helpers; status output now shows auto-apply window + last apply.
- `bot/engine.py` — added `request_restart()`, `_perform_self_restart()`, wired the callback to `AuditorService`. Imports `os` + `sys`. Restart fires from the `finally` block of `run()` after `shutdown()` so all services stop cleanly.
- `config.py` + `.env.example` — six new `AUDITOR_AUTOAPPLY_*` env vars.
- `tests/test_auditor.py` — eight new tests covering each gate (disabled, in-window high-severity success, outside window, low severity skip, per-night cap, broker paused, state round-trip, restart-disabled, cross-midnight window).

## How to enable (and how to back out)

```
# In .env
AUDITOR_AUTOAPPLY_ENABLED=1
AUDITOR_AUTOAPPLY_WINDOW_START_HOUR=1
AUDITOR_AUTOAPPLY_WINDOW_END_HOUR=7
AUDITOR_AUTOAPPLY_MIN_SEVERITY=high
AUDITOR_AUTOAPPLY_MAX_PER_NIGHT=1
AUDITOR_AUTOAPPLY_RESTART_ENABLED=1
```

To back out:

- Disable the feature: `AUDITOR_AUTOAPPLY_ENABLED=0` and restart. No code change required.
- Undo a specific override that auto-apply wrote: send `Auditor -revert <KNOB>` in Discord (works the same as manual confirms).
- Inspect what auto-apply has done: `Auditor -status` shows the last auto-apply knob, value, timestamp, and night counter.

## Risks / open questions

- **Restart reliability on Windows.** `os.execv` works on Windows but can leave a brief blank console as the new process attaches. Catch is in place: if `os.execv` raises we exit with code `75` so a supervisor (nssm/systemd/etc.) can re-launch us. With no supervisor configured, the bot will simply stop and the user has to relaunch manually. The Discord auto-apply message says "Bot is restarting now" — if that's followed by **no startup pin** in the next minute, restart failed.
- **Concurrent auto-applies across nights.** The night-key bookkeeping resets only when the auditor *actually runs* during the new night. If the bot is offline at 1 AM and only starts at 8 AM, no auto-apply that night — expected behavior.
- **Severity calibration.** Only one current proposer rule emits `high` severity (forecast central tendency negative across all horizons). If you want more aggressive auto-apply, drop `AUDITOR_AUTOAPPLY_MIN_SEVERITY=medium`, but understand that the win-rate rule and fee-drag rules emit `medium` regularly — that's a more frequent change.
- **No rollback on bad outcome.** Auto-apply does not include any "if PnL drops X% within Y minutes, automatically revert" logic. That's a separate follow-up.
- **Forced restart while a trade is mid-execution.** The cooperative shutdown waits for the current tick to finish before exiting, and `os.execv` happens 2 s later — but if a Kraken call is in progress, the new process won't know about it. Paper-trading-only mitigates this; revisit before any live wiring.
