# Pattern library

Small, reusable code snippets that have proven themselves in this codebase. Copy these when starting something new — don't reinvent.

## 1. Frozen settings + helper

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class FooSettings:
    enabled: bool = False
    threshold: float = 1.0
    backoff_sec: float = 0.5

def load_foo(env) -> FooSettings:
    return FooSettings(
        enabled=env.get("FOO_ENABLED", "0") == "1",
        threshold=float(env.get("FOO_THRESHOLD", "1.0") or 1.0),
        backoff_sec=float(env.get("FOO_BACKOFF_SEC", "0.5") or 0.5),
    )
```

- Always provide defaults inside `dataclass`.
- `env.get(...) or DEFAULT` to absorb empty strings.

## 2. Retry with backoff + cache fallback

```python
import logging
import time
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)
T = TypeVar("T")

_RETRYABLE = (ConnectionError, TimeoutError)

def retry(label: str, fn: Callable[[], T], *, max_retries: int, backoff: float) -> T:
    last: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except _RETRYABLE as exc:
            last = exc
            if attempt >= max_retries:
                break
            wait = backoff * (2 ** attempt)
            logger.warning("%s failed (%s), retry in %.2fs", label, exc, wait)
            time.sleep(wait)
    assert last is not None
    raise last

def fetch_with_cache(key, fetcher, cache: dict, *, max_retries=2, backoff=0.5):
    try:
        result = retry(f"fetch[{key}]", fetcher, max_retries=max_retries, backoff=backoff)
        cache[key] = result
        return result
    except _RETRYABLE:
        if key in cache:
            logger.warning("fetch[%s] failed; using cached value", key)
            return cache[key]
        raise
```

## 3. Cooperative thread shutdown

```python
import threading

class Service:
    def __init__(self):
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._do_one_iteration()
            except Exception:
                import logging
                logging.getLogger(__name__).exception("iteration failed")
            self._stop.wait(self.interval_sec)   # interruptible sleep
```

Key points:
- `Event.wait(interval)` is interruptible; `time.sleep` is not.
- Per-iteration `try/except Exception` so one failure doesn't kill the loop.
- `daemon=True` is a safety net, not the primary shutdown mechanism.

## 4. Persisted state dataclass

```python
from dataclasses import dataclass, field, asdict
from pathlib import Path
import json

@dataclass
class Snapshot:
    last_value: float = 0.0
    history: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Snapshot":
        return cls(
            last_value=float(data.get("last_value", 0.0)),
            history=[float(x) for x in data.get("history", [])],
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> "Snapshot":
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return cls()
        return cls.from_dict(data)
```

Atomic write via `.tmp` + `replace` avoids torn files on crash.

## 5. Defensive intent emitter

When a constraint detects an out-of-policy holding, it emits a `TradeIntent` flagged defensive:

```python
TradeIntent(
    from_asset="ADA",
    to_asset="ETH",
    reason="alt cap: ADA at 51% > 40%",
    size_pct=trim_fraction,
    edge=0.0,
    is_defensive=True,
    strategy_name="portfolio_constraints",
)
```

The orchestrator/governor must keep `is_defensive` intents first in the queue and skip the edge ranking for them.

## 6. Wall-clock vs. monotonic decision tree

```
Does this value get written to disk / persisted across restarts?
├── Yes  → time.time()  (wall-clock)
└── No
    ├── Is it compared across process restarts?
    │   ├── Yes → time.time()
    │   └── No  → time.monotonic()  (immune to clock changes)
    └── (default to monotonic for in-process timers)
```

## 7. Discord message + chat-log mirror

```python
def post_important(self, content: str, *, pin: bool = False) -> None:
    msg_id = self._send(content)
    if pin and msg_id:
        self._pin(msg_id)
    self.chat_log.log_outbound("important", content)
```

Always mirror outbound messages to `chat_log` — never branch the mirroring logic into a conditional. If the message is sent, it must be logged.
