# Logging conventions

## Level policy

| Level | When to use |
|---|---|
| `CRITICAL` | The bot cannot continue — imminent crash or data-corruption risk. |
| `ERROR` | An operation failed and the bot cannot complete the current unit of work (e.g. API call failed after all retries, order rejected). Always actionable. |
| `WARNING` | Something degraded or unexpected that the **user should eventually see**, but the bot can continue (e.g. fee schedule fallback to env default, watchdog cannot reach a file, stale state pruned on load). |
| `INFO` | Normal operational milestones that confirm expected behavior (e.g. fee schedule loaded successfully, auditor ran, strategy selected). Verbose but not noisy. |
| `DEBUG` | Fine-grained detail for developer tracing (tick internals, individual price lookups, cache hits). Off by default in production. |

### Decision heuristic

Ask: *"Would I want to see this message if I woke up and read the log?"*

- **Yes, it's a problem or degradation** → `WARNING` or `ERROR`.
- **Yes, it confirms something worked** → `INFO`.
- **No, it's tick-level noise** → `DEBUG`.

## Common mistakes to avoid

| Pattern | Fix |
|---|---|
| `logger.warning("Fee schedule loaded OK …")` | Use `logger.info` — success is not a warning. |
| `logger.info("API call failed: %s", exc)` | Use `logger.warning` or `logger.error` — failures are not informational. |
| `logger.warning("tick start")` | Use `logger.debug` — high-frequency events do not belong above DEBUG. |
| Bare `except: logger.error(…)` | Always catch a specific exception family; use `except Exception as exc` with `# noqa: BLE001` only when a broad catch is intentional. |

## Module sweep status

| Module | Status |
|---|---|
| `bot/fee_engine.py` | Fixed 2026-05-31 — success paths changed from WARNING → INFO. |
| `bot/auditor/state.py` | Correct — uses WARNING only for parse failures and stale-state pruning. |
| `watchdog/state.py` | Correct — no spurious WARNING on success. |
| `bot/paper_broker.py` | No logger — uses exception propagation only. |
| `bot/risk.py` | No logger — uses return values only. |
| All others | Pending sweep. |
