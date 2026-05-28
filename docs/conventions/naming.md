# Naming conventions

## Files and modules

| Kind | Convention | Example |
|------|------------|---------|
| Module file | `lower_snake_case.py` | `portfolio_constraints.py` |
| Strategy plugin | `<strategy_name>.py` in `bot/strategies/` | `cross_momentum.py` |
| Test file | `test_<feature>.py` matching `feature_logs/NNN_<feature>.md` | `test_portfolio_constraints.py` |
| Doc file | `lower-kebab-case.md` | `tick-lifecycle.md` |
| Feature log | `NNN_short-name.md` (zero-padded, kebab) | `006_watchdog-four-bugs.md` |

## Python identifiers

| Kind | Convention | Example |
|------|------------|---------|
| Class | `PascalCase` | `PortfolioConstraints`, `StrategyGovernor` |
| Public function/method | `lower_snake_case` | `validate_intent`, `record_trade` |
| Private/internal | `_leading_underscore` | `_holdings`, `_post_alert` |
| Constant | `UPPER_SNAKE_CASE` | `MIN_USD_TRADE`, `WALL_CLOCK_MIN` |
| Type variable | Single capital | `T`, `K`, `V` |
| Enum | `PascalCase` class, `UPPER_SNAKE` values | `Signal.BUY`, `Signal.SELL` |
| Dataclass | `PascalCase` with descriptive suffix | `TradeIntent`, `TradeGate`, `HealthReport` |

## Environment variables

`UPPER_SNAKE_CASE`, grouped by subsystem prefix:

| Prefix | Subsystem |
|--------|-----------|
| `KRAKEN_*` | Exchange / data fetch |
| `TRADE_*`, `MIN_*`, `MAX_*` | Trading rules |
| `DISCORD_*` | Discord client |
| `WATCHDOG_*` | Watchdog monitor |
| `STRATEGY_*` | Strategy governance |
| `IDLE_*` | Adaptive relaxation |
| `CIRCUIT_BREAKER_*` | Drawdown protection |
| `STAT_ARB_*` | Stat arb strategy |
| `MOMENTUM_*` | Cross/momentum strategy |

## Booleans

- Use `is_`, `has_`, `can_`, `should_` prefixes on properties and predicates.
- Examples: `is_defensive`, `has_recent_errors`, `can_pin`, `should_alert_error`.

## Trading-domain terms

Use these consistent terms; do not invent synonyms.

| Term | Meaning |
|------|---------|
| **edge** | Expected return percentage (decimal, e.g. `0.005` = 0.5%) |
| **hops** | Number of pair conversions in a trade route (1 = direct, 2 = via cross pair) |
| **route / path** | Ordered list of legs to convert from `from_asset` to `to_asset` |
| **intent** | A proposed trade not yet executed (`TradeIntent`) |
| **leg** | One pair-level conversion within a route |
| **swap** | A direct held-to-held conversion (e.g. ETH↔ADA via ADA/ETH) |
| **rotation** | Selling one alt and buying another |
| **defensive** | Trade required by risk policy, bypasses some gates |
| **adaptive** | Idle relaxation mode loosening edge/net thresholds |
| **dominant strategy** | Last strategy to execute a trade; eligible for stickiness |
| **growth window** | Rolling time window used to evaluate strategy performance |
| **circuit breaker** | Hard drawdown halt requiring manual `resume-trading` |
| **hibernate** | Timed drawdown pause (auto-recovers after `HIBERNATE_HOURS`) |

## Imports

```python
# stdlib
import json
import logging
from pathlib import Path

# third-party
import ccxt
import pandas as pd

# first-party (alphabetical, absolute paths from project root)
from bot.local_time import format_pacific
from bot.strategies.base import TradeIntent
from config import Settings
```

- One blank line between groups.
- No relative imports (`from .foo` etc.).
- Use `from __future__ import annotations` for all new modules.

## Logging keys

When using structured-ish log messages, follow `Subsystem: action — details`:

```
logger.warning("Kraken fetch_ticker(%s) timed out (attempt %d/%d)", ...)
logger.info("Watchdog thread started")
```

Avoid emoji in log lines (terminal compatibility); reserve them for Discord output if explicitly requested.
