# Code patterns

Reusable patterns the codebase already follows. New code should match.

## 1. Configuration

All runtime configuration flows through a single frozen `Settings` dataclass in `config.py`. Modules accept the slice they need, never `os.getenv` directly.

```python
# Good
class WatchdogService:
    def __init__(self, settings: Settings, ...):
        self.enabled = settings.watchdog_enabled

# Bad
class WatchdogService:
    def __init__(self):
        self.enabled = os.getenv("WATCHDOG_ENABLED") == "1"  # ← scattered config
```

Add new settings to:
1. `Settings` dataclass field
2. `load_settings()` reader with safe default
3. `.env.example` documenting the knob
4. `.env` if the user runs with a non-default value

## 2. Dataclass results

Return small frozen dataclasses instead of multi-element tuples.

```python
# Good
@dataclass(frozen=True)
class ConstraintResult:
    allowed: bool
    size_pct: float
    reason: str = ""

def validate_intent(...) -> ConstraintResult: ...

# Bad
def validate_intent(...) -> tuple[bool, float, str]: ...
```

## 3. Wall-clock vs. monotonic time

- **Persisted to disk** → `time.time()` (survives restart, comparable across processes).
- **In-memory only, no persistence** → `time.monotonic()` (immune to clock changes).

Mixing these has caused bugs. See `feature_logs/006`.

## 4. Retry with backoff and cache fallback

Network calls follow this shape:

```python
def fetch(...):
    try:
        result = self._retry("op_label", lambda: self.client.call(...))
        self._cache[key] = result
        return result
    except _RETRYABLE as exc:
        cached = self._cache.get(key)
        if cached is not None:
            logger.warning("op %s failed; using cached", key)
            return cached
        raise
```

`_retry` does exponential-ish backoff, catches a tuple of retryable exception types, and re-raises after `max_retries`. See `bot/data.py`.

## 5. Cooperative thread shutdown

Long-lived threads expose:

- `start()` — idempotent
- `stop()` — sets a `threading.Event`, sends any in-progress work an abort signal, joins with a short timeout
- Internal loop checks the stop event between substantive operations (not just `time.sleep`)

`bot/watchdog_service.py` is the reference.

## 6. Discord posting

Three layers:

| Method | When to use |
|--------|-------------|
| `discord.post_plain(text)` | Startup messages, heartbeats — fire-and-forget |
| `discord.post_important(text, pin=)` | Status changes, trades, milestones — may pin |
| `discord.post_error(context, exc)` | Errors — deduped, gated by `>3 in 30 min` for pinning |

All three mirror to `logs/discord_chat.log` automatically via `DiscordChatLog`.

## 7. Strategy plugin contract

```python
class MyStrategy(Strategy):
    name = "my_strategy"

    def evaluate(
        self,
        candles: dict[str, pd.DataFrame],
        prices: dict[str, float],
        holdings: dict[str, float],
        *,
        risk: RiskManager | None = None,
        markets: Markets | None = None,
        context: StrategyContext | None = None,
    ) -> StrategyResult:
        intents = []
        # populate intents; each MUST set strategy_name (orchestrator falls back to self.name)
        return StrategyResult(
            signals={}, scores={}, reasons={}, sizes={},
            intents=intents,
        )
```

Plugin rules:
- Never call exchange APIs directly — use `candles` / `prices` / `context`.
- Never mutate `risk`, `markets`, or holdings.
- Stay deterministic for the same input.
- Set `gross_return_pct` on intents so the orchestrator can rank correctly.

## 8. State persistence

```python
@dataclass
class FooState:
    ...
    def save(self, path: Path) -> None: ...
    @classmethod
    def load(cls, path: Path) -> "FooState": ...
```

- `from_dict` / `to_dict` for back-compat across field additions.
- Always tolerate missing keys; provide sane defaults.
- Migrate / drop invalid values silently on load (e.g. stale monotonic timestamps).

## 9. Errors and logging

```python
try:
    self._do_thing()
except SpecificError as exc:
    logger.warning("Subsystem: did not do thing — %s", exc)
except Exception:
    logger.exception("Subsystem: unexpected failure")  # full traceback
```

- Never `except:` without a type (catches `KeyboardInterrupt`).
- `logger.exception` only inside an `except` block.
- Errors that should reach Discord go through `engine._report_error(context, exc)`.

## 10. Test patterns

- Use `pytest.fixture` for shared setup.
- Mock external services (`unittest.mock.patch`); never hit live Kraken or Discord.
- `tmp_path` fixture for any disk state.
- One assertion concept per test; multiple `assert`s OK if they describe the same behaviour.
