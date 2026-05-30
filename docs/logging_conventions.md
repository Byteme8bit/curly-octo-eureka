# Logging conventions

This document is the single source of truth for log levels used throughout
`bot/`. When in doubt, ask: _would an operator monitoring the live terminal
want to see this without digging?_

## Level policy

| Level | Use when | Examples |
|-------|----------|---------|
| `logger.error(...)` | Something broke and the bot **cannot self-recover** in this tick — human attention required. Reserve for hard failures that propagate up or halt a subsystem. | Order placement rejected by exchange; state file write failed after all retries. |
| `logger.warning(...)` | Something unexpected happened but the bot **recovered or degraded gracefully**. Operator should see it in a glance. | Kraken rate-limited → using cached price; fee schedule unavailable → fell back to env default; state file corrupt → starting fresh. |
| `logger.info(...)` | Normal, expected behaviour the operator might care about at startup or on a state change. Not repeated on every tick. | Fee schedule loaded successfully; strategy switched; circuit breaker engaged or released. |
| `logger.debug(...)` | High-frequency detail useful for debugging a specific issue. Never shown in production unless log level is lowered. | Per-tick candle counts; cache hit/miss; individual order legs. |

## Common misuse patterns to avoid

### WARNING for success

```python
# Bad — WARNING implies something is wrong
logger.warning("Fee source: PERSONALISED — %d pair(s) loaded", n)

# Good — INFO for a normal startup milestone
logger.info("Fee source: PERSONALISED — %d pair(s) loaded", n)
```

### Silent I/O failure

```python
# Bad — caller gets None with no log; hard to diagnose
try:
    data = json.loads(path.read_text())
except (OSError, json.JSONDecodeError):
    return None

# Good — always log why the fallback was taken
try:
    data = json.loads(path.read_text())
except (OSError, json.JSONDecodeError) as exc:
    logger.warning("State file unreadable (%s); starting fresh — %s", path, exc)
    return None
```

### Swallowing unexpected exceptions

```python
# Bad — a programming error (TypeError, etc.) is silently hidden
except Exception:
    pass

# Good — at minimum log at WARNING; use logger.exception for tracebacks
except Exception as exc:   # noqa: BLE001
    logger.warning("Subsystem: unexpected error — %s", exc)
```

## Module coverage

Every module that performs I/O, state mutations, or retryable network calls
**must** have a module-level logger:

```python
import logging
logger = logging.getLogger(__name__)
```

Modules that are purely computational (no I/O, no side effects) may omit
the logger if they have nothing meaningful to report.

## Format

Follow `Subsystem: action — detail` for message text:

```python
logger.warning("FeeEngine: public schedule load failed — %s", exc)
logger.info("FeeEngine: fee source PERSONALISED — %d pairs loaded%s", n, sample)
logger.warning("WatchdogState: state file unreadable; starting fresh — %s", exc)
```

No emoji in log lines (terminal compatibility). Emoji belong in Discord output.
