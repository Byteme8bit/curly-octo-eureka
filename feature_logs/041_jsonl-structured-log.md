# Feature 041 — feat(logging): JSONL structured log sink

## Status
completed

## Problem
All bot logs were free-text, making programmatic analysis (PnL trends, fee
distribution, strategy attribution over time) difficult without parsing
human-readable strings.

## Fix
Created `bot/structured_log.py` — a thread-safe, append-only JSONL writer.

`StructuredLogger` exposes:
- `log_trade(trade: dict)` — emits a `"trade"` JSONL record
- `log_preflight_reject(...)` — emits a `"preflight_reject"` JSONL record

`BotFileLogger` in `bot/trade_log.py` now creates a `StructuredLogger` on
construction and calls `log_trade()` for every filled trade in `log_tick()`.
The file is written to `<log_dir>/events.jsonl` alongside the existing
human-readable log files.

Pre-flight reject wiring is available via `log_preflight_reject()` for any
caller that has access to a `StructuredLogger` instance; engine wiring is a
follow-on task.

## Schema
```json
{"ts":"2026-06-07T00:10:00+00:00","event":"trade","strategy":"momentum_rotation",
 "from_asset":"USD","to_asset":"ETH","from_qty":500.0,"to_qty":0.25,
 "fee_usd":2.0,"gain_loss":0.0,"type":"usd","hops":1,"reason":"ETH leads"}

{"ts":"2026-06-07T00:09:55+00:00","event":"preflight_reject",
 "strategy":"triangular_arbitrage","from_asset":"ETH","to_asset":"ETH",
 "gross_pct":0.0012,"fee_pct":0.004,"slippage_pct":0.0005,
 "net_pct":-0.0033,"threshold":0.001,"reason":"Pre-flight reject: ..."}
```

## Files changed
- `bot/structured_log.py` — new module
- `bot/trade_log.py` — `BotFileLogger.__init__` creates `StructuredLogger`;
  `log_tick` forwards filled trades
- `tests/test_structured_log.py` — 8 tests covering both event types and
  `BotFileLogger` integration

## Verification
```
pytest tests/test_structured_log.py -v
```
