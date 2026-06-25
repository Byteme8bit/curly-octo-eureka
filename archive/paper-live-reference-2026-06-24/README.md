# Paper / Live Reference Snapshot — 2026-06-24

**"What coulda been"** — preserved state from the live-mirror experiment before resetting to paper-only mode.

## Why this archive exists

The bot ran **live mirror mode** from 2026-06-14 through 2026-06-19: paper strategies executed freely while selected routes mirrored to real Kraken spot. This folder captures the portfolio and state files at the moment we stepped back to **paper-only** with a fresh baseline anchored to actual Kraken balances.

## Portfolio at archive time (Kraken truth)

| Asset | Qty | ~USD |
|-------|-----|------|
| **ETH** | 0.7101 | $1,168 |
| **USD** | 415.90 | $416 |
| **ADA** | 24.56 | $3.68 |
| **BTC** | 0.000015 | $0.92 |
| **ATOM** | 0.179 | $0.30 |
| **USDC** | 0.305 | $0.30 |
| **Total** | | **~$1,589** |

*Timestamp: 2026-06-24 UTC fetch via Kraken API.*

## Session context

| Metric | Value |
|--------|-------|
| Live session anchor (re-anchored) | $1,203 on 2026-06-19 |
| Original live start growth window | ~$1,654 (2026-06-14) |
| Peak referenced in handoff | ~$1,724 |
| Live trades completed | 22 |
| Live fees paid (sum) | ~$10.38 |

## Files in this archive

| File | Purpose |
|------|---------|
| `.paper_state.json` | Paper sim — diverged from Kraken (phantom DOT/UNI routes) |
| `.live_state.json` | Real Kraken trade history + balances |
| `live_session_start.json` | Session anchor, peak, halt threshold |
| `.futures_paper_state.json` | Futures paper sim (distraction) |
| `.tradebot_goals_state.json` | Goal evolution progress |
| `logs/trade_diagnosis.json` | Last idle/block diagnosis snapshot |
| `receipts-summary/` | Sample of trade receipt `.txt` files |

## What paper "coulda been"

Paper continued trading triangular arb, bucket trims, and multi-hop routes that either **never mirrored** to live (leg limits, allowed-asset guards, negative-net blocks) or **lost money** when they did (4-leg triangular loops, defensive momentum sells). The inflated paper book made Discord/dashboard PnL misleading relative to the ~$1,589 Kraken wallet.

## Next steps (post-archive)

1. Paper-only mode: `LIVE_ENABLED=0`, `STRATEGIES=cross_momentum,stat_arb`
2. Fresh baseline: `paper_baseline.json` (gitignored) + `scripts/anchor_paper_to_live.py --paper-only`
3. Re-read `docs/LIVE_ATTEMPT_POSTMORTEM.md` before any future live attempt

*Do not delete originals in repo root until paper reset is verified.*
