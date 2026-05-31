# Logging Conventions

This document defines the log-level policy for all Python modules in
`bot/` and `watchdog/`. Follow it when adding new log calls, and apply
it when auditing existing ones.

---

## Level reference

| Level | When to use | Examples |
|---|---|---|
| `DEBUG` | Low-level diagnostic detail useful only during development. Normally filtered out. | Raw API response payloads, tick-level math intermediates, cache hit/miss. |
| `INFO` | Normal informational events. The operator reads INFO to understand what the bot is doing. | Service started or stopped, resource loaded successfully, audit ran, trade evaluated (even if rejected), scheduled job completed. |
| `WARNING` | Something degraded but the bot is continuing. The operator should be aware but no action is required right now. | API call failed and a fallback was used, optional external resource unavailable, non-critical file write failed, rate-limit back-off triggered. |
| `ERROR` / `exception` | A feature or subsystem failed in a way that may require operator action or investigation. | Fatal startup error, uncaught exception in a background thread, persistent I/O failure after retries. |
| `CRITICAL` | Reserved for events that make the whole process unrecoverable. Extremely rare. | — |

---

## Decision rules

1. **Success → INFO.** If an operation completed as intended, log at INFO.
   Do not log a successful path at WARNING just because the call-site is
   inside an exception handler that also logs failures.

2. **Fallback → WARNING.** If the primary path failed but a known
   fallback kept the bot running, log the fallback at WARNING so the
   operator knows something unexpected happened.

3. **Startup lifecycle → INFO.** Service-start/stop messages
   (`"Foo service started"`, `"Listener stopped"`) are normal operational
   events; use INFO, not WARNING.

4. **Skip this iteration → INFO.** When a scheduled check decides "nothing
   to do" (e.g. auto-apply per-night cap reached, audit window missed),
   INFO is appropriate — it's not a problem.

5. **Repeated transient failures → WARNING each occurrence.** API timeouts
   or 429 rate-limits that are retried should each be WARNING, not INFO,
   so operators can spot saturation in the logs.

6. **Exception caught, re-raised or unhandled → ERROR.** Use
   `logger.exception(...)` (which includes the traceback automatically)
   for any `except` block that is the final stop for an error that
   shouldn't have happened.

---

## Anti-patterns to avoid

```python
# BAD — success logged at WARNING
logger.warning("Fee source loaded — %d pairs", n)

# GOOD
logger.info("Fee source loaded — %d pairs", n)

# BAD — startup event at WARNING
logger.warning("Discord command listener started")

# GOOD
logger.info("Discord command listener started")

# BAD — swallowing the exception without logging
except Exception:
    pass

# GOOD — log it, even if you can't re-raise
except Exception as exc:
    logger.warning("Foo failed (%s); continuing with default", exc)
```

---

## Module status (last audited 2026-05-31)

| Module | Status |
|---|---|
| `bot/fee_engine.py` | Fixed: success paths demoted from WARNING to INFO |
| `bot/discord_bot.py` | Fixed: startup message demoted from WARNING to INFO |
| `bot/auditor_service.py` | Consistent — no changes needed |
| `bot/engine.py` | Consistent — no changes needed |
| `bot/auditor/state.py` | Consistent (fixed in PR #8/#9) |
| `bot/data.py` | Consistent — WARNING on all API failures |
| `bot/auditor/news_client.py` | Consistent — WARNING on provider failures |
| `watchdog/` | Consistent — minimal logging, appropriate levels |
