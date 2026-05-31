# Logging conventions

All bot and watchdog modules import Python's standard `logging` library and
obtain a per-module logger:

```python
import logging
logger = logging.getLogger(__name__)
```

## Level policy

| Level | When to use | Visible at default log level? |
|---|---|---|
| `logger.error(...)` | Unrecoverable failure within a single operation; the action it was trying to perform will **not** complete. Always log the exception. | Yes |
| `logger.warning(...)` | A **degraded** path was taken that the operator should know about: a fallback was used, a retry exhausted, an optional feature disabled, a malformed record skipped. Something did NOT go as intended, but the bot is still running. | Yes |
| `logger.info(...)` | Normal, expected lifecycle events: a background service started/stopped, a schedule fired, a successful operation that is worth knowing happened (e.g. "Fee schedule loaded"). | Only in verbose setups |
| `logger.debug(...)` | High-frequency, loop-level detail useful only when actively debugging. Should never appear in production at the default level. | No |

### Common misclassifications to avoid

- **SUCCESS + WARNING**: A fee schedule loaded successfully with personalised
  data — that is `INFO`, not `WARNING`. `WARNING` signals to the operator that
  something is wrong or degraded.
- **STARTUP INFO as WARNING**: "Watchdog command listener started" is `INFO`;
  "Watchdog alert delivery failed" is `WARNING`.
- **Noisy retry loops**: Individual retry attempts inside a loop should be
  `DEBUG`; the final failure (if all retries exhausted) should be `WARNING`.

## Exception logging

Always name the exception variable and include it in the log message:

```python
# Good
try:
    ...
except ccxt.AuthenticationError as exc:
    logger.warning("Auth failed: %s", exc)

# Bad — bare except
try:
    ...
except:
    pass

# Bad — swallows detail
except Exception:
    logger.warning("Something failed")
```

Use `logger.exception(...)` (equivalent to `logger.error` + traceback) only
for unexpected, unhandled exceptions at a top-level boundary where the full
traceback is genuinely useful for debugging.

## Message format

- Use `%`-style formatting (`logger.info("x=%s", x)`) — do **not** f-string
  inside the log call, because the formatting is skipped entirely if the log
  level is filtered out.
- Keep messages terse and factual. Bad: `"Successfully loaded the fee schedule
  from Kraken!"`. Good: `"Fee source: PUBLIC — 147 pairs loaded"`.
- Include the key value(s) that distinguish one log line from another when
  they appear in a loop (symbol name, proposal id, etc.).

## Module-specific notes

| Module | Notes |
|---|---|
| `bot/fee_engine.py` | Successful fee-schedule loads → `INFO`. Fallback to env default → `WARNING`. |
| `bot/auditor/state.py` | Malformed records on load → `WARNING`. Expired-proposal prune → `WARNING` (degraded state recovered). |
| `watchdog/state.py` | State-file corrupt → use Python default logger at `WARNING` (no module logger in dataclass). |
| `bot/auditor_service.py` | Service start/stop lifecycle → `INFO`. Auto-apply refused → `WARNING`. |
| `bot/discord_bot.py` | Discord API failures → `WARNING`. Listener lifecycle → `WARNING` (Discord connectivity is user-visible). |
