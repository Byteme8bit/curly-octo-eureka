# Independent trade verification

The **Independent Verifier** audits TradeBot paper trades without trusting Discord or bot self-reporting alone. It reads primary sources (`.paper_state.json`, `receipts/`, session logs) and optionally compares fills to **Kraken public market data** via ccxt (no API keys required).

## Quick start

```powershell
# Review all trades in .paper_state.json
.\.venv\Scripts\python.exe scripts\verify_trades.py

# Last 20 trades only
.\.venv\Scripts\python.exe scripts\verify_trades.py --last 20

# Trades since a date
.\.venv\Scripts\python.exe scripts\verify_trades.py --since 2026-06-01

# Save JSON + HTML reports
.\.venv\Scripts\python.exe scripts\verify_trades.py --json --html reports/verification.html -v

# Offline (no Kraken API) — correlation and constraints only
.\.venv\Scripts\python.exe scripts\verify_trades.py --skip-kraken
```

Equivalent module entry:

```powershell
.\.venv\Scripts\python.exe -m bot.verifier --last 10 --json
```

## What it checks

| Check | Source | CONFIRM | DENY | UNCERTAIN |
|-------|--------|---------|------|-----------|
| Existence & correlation | `receipts/`, `logs/*_PDT.log` | Receipt + log match | Missing receipt | Receipt OK, log missing/rotated |
| Market reality | Kraken `load_markets()` | Pair exists | Unknown pair/asset | API skipped |
| Price plausibility | Kraken OHLCV @ trade time | Fill within candle ± tolerance | Impossible fill | OHLCV unavailable |
| Fee realism | Kraken taker schedule vs `fee_usd` | Within tolerance | Large mismatch | Paper `FEE_RATE` ≠ live Kraken |
| Size & constraints | Replay balances + `PortfolioConstraints` | Passes reserve/min/alt cap | ETH reserve / min USD breach | Alt cap edge case |
| Multi-hop / triangular | Trade `type`, `reason`, strategy | Single-leg USD trade | — | Multi-leg or triangular loop |
| Pre-flight | `PreFlightValidator` + live fees | Net profit OK | Would reject | Skipped offline |
| Liquidity hint | 24h quote volume vs trade USD | Small vs volume | — | Large vs alt volume |

## Verdict meanings

- **CONFIRM** — All checks passed or only benign skips. This trade plausibly could have executed on Kraken under the bot's rules.
- **DENY** — At least one hard failure: missing receipt, unknown market, impossible price, fee far from Kraken, constraint violation, or pre-flight reject. Treat as **not live-viable as recorded**.
- **UNCERTAIN** — Mixed or soft issues: triangular/multi-hop atomicity, log rotation, paper fee assumption vs live schedule, liquidity slippage risk, or unavailable Kraken data. Review manually before going live.

Session summary includes counts of each verdict, paper PnL and fee drag for reviewed trades, and **systematic issues** (e.g. many triangular routes).

## Configuration

Optional `.env` knobs (see `.env.example`):

| Variable | Default | Purpose |
|----------|---------|---------|
| `VERIFIER_PRICE_TOLERANCE_PCT` | `0.02` | Allowed deviation from OHLC candle |
| `VERIFIER_SLIPPAGE_ASSUME_PCT` | `0.005` | Extra slippage added to price tolerance |
| `VERIFIER_FEE_TOLERANCE_REL` | `0.15` | Relative fee mismatch before DENY |
| `VERIFIER_LIQUIDITY_WARN_RATIO` | `0.01` | Trade USD / 24h volume → UNCERTAIN |
| `VERIFIER_LOG_WINDOW_MINUTES` | `30` | Log correlation window |
| `VERIFIER_SKIP_KRAKEN` | `0` | Set `1` to skip all Kraken calls |

Portfolio rules reuse `MIN_ETH_RESERVE`, `MAX_ALT_ALLOCATION_PCT`, `MIN_USD_TRADE`, `SLIPPAGE_BUFFER_PCT`, and `MIN_NET_PROFIT_PCT`.

## Output

- **stdout** — Human-readable summary; non-CONFIRM trades listed by default (`--verbose` for all).
- **`reports/verification_YYYYMMDD-HHMMSS.json`** — Full structured report when `--json` is passed.
- **`--html PATH`** — Simple HTML table for sharing.

Exit code `1` if any **DENY** verdicts exist (useful for CI/scripts).

## Architecture

```
scripts/verify_trades.py     → bot.verifier.__main__
bot/verifier/
  config.py    — settings from env + config.load_settings()
  parsers.py   — state/receipt/log correlation, balance replay
  kraken.py    — public ccxt wrapper (OHLCV, fees, volume)
  checks.py    — per-check functions
  core.py      — Verifier orchestration
  report.py    — text / JSON / HTML output
```

Reuses `watchdog.parsers`, `bot.fee_engine.FeeEngine`, `bot.preflight.PreFlightValidator`, and `bot.portfolio_constraints.PortfolioConstraints`.

## Interpreting results for go-live

1. Run on full history: `python scripts/verify_trades.py --json`
2. If **DENY** count > 0, inspect `--verbose` output — fix data integrity or bot logic before live.
3. High **UNCERTAIN** from triangular/multi-hop is expected for arb strategies; live needs atomic execution or acceptance of leg risk.
4. Compare `estimated_fee_drag_usd` to paper PnL — if fees dominate, paper edge may not survive live taker rates.
