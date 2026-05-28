# 008 — Kraken API timeout + retry with backoff

**Requested:** 2026-05-25
**Status:** complete

## Request
> Also, the kraken API has timedout several times trying to fetch data. Can we implement a shorter wait and retry in between the 12s if this is encountered possibly?

## Actions taken
- **Rewrote `bot/data.py`** with `_retry(label, fn)` helper:
  - Catches `ccxt.NetworkError`, `RequestTimeout`, `ExchangeNotAvailable`, `DDoSProtection`
  - Exponential-ish backoff (default 0.75s → 1.5s → 3s)
  - Per-call timeout set on the ccxt instance
- Added in-memory caches (`_ticker_cache`, `_candle_cache`) for graceful degradation — if all retries fail, last good value is used and a warning is logged instead of crashing the tick
- Worst-case timing: 5s + 0.75s + 5s + 1.5s = **~12.3s** total (fits inside 15s poll interval)
- **`config.py`** — added 3 settings
- **`.env`** + **`.env.example`** — added under "Kraken API timeout + retry"

## New config
| Setting | Default | What it does |
|---|---|---|
| `KRAKEN_REQUEST_TIMEOUT_MS` | 5000 | Per-request HTTP timeout (down from ccxt default 10s) |
| `KRAKEN_MAX_RETRIES` | 2 | Retry attempts after first failure |
| `KRAKEN_RETRY_BACKOFF_SEC` | 0.75 | Initial backoff (doubles each attempt) |

## Verification
Retry warnings log as:
```
Kraken fetch_ticker(BTC/USD) timed out (attempt 1/3): RequestTimeout — retrying in 0.8s
```

## Notes
- Parallel candle fetches now tolerate per-symbol failure without crashing the whole tick — failed symbols are just missing from the result dict that pass.
