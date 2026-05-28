# Tests

Pytest-based regression suite. Each feature with non-trivial logic gets a `test_<feature>.py`.

## Running

```powershell
cd C:\Users\lynch\eth-trading-bot
.\.venv\Scripts\python.exe -m pytest
```

## Layout

| File | Covers feature |
|------|----------------|
| `test_portfolio_constraints.py` | 001 — ETH floor and alt allocation cap |
| `test_strategy_governor.py` | 002 — Stickiness + growth-based switching |
| `test_watchdog_state.py` | 006 — Wall-clock timestamps, error categorization, pin threshold |
| `test_kraken_retry.py` | 008 — Retry-with-backoff + cache fallback |

## Convention

- One test file per `feature_logs/NNN_*.md` feature where it makes sense.
- Test names describe the behaviour, not the implementation (`test_eth_sell_clamped_to_reserve`, not `test_clamp_eth_sell_size_branch`).
- Use `pytest.fixture` for shared setup; avoid global mutable state.
- Mock external services (Kraken, Discord); never hit a live API in tests.
- Use `tmp_path` for any filesystem state.

## Required after each feature

The agent must add or update tests in this folder before declaring a feature complete (see `docs/conventions/verification.md`).
