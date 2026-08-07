# 094 — Seed USD arb inventory + tighter stat-arb

**Requested:** 2026-08-07 00:08 PDT
**Status:** complete

## Request
PERMISSION GRANTED: seed USD into arb inventory + tighten stat-arb

## Actions taken
VPS only (kept real `FEE_FORCE_STATIC=0` / 0.40%):
- Kept screenshot ETH `0.52042`
- Spent **$250 USD** → ~$120 ADA, $80 BTC, $50 SOL (USD left **165.90**)
- `STAT_ARB_ZSCORE_THRESHOLD=1.2`, `STAT_ARB_LOOKBACK=24`, `DUST_USD=5`
- Updated `INITIAL_BALANCES`; archived prior → `archive/2026-08-07-arb-inventory-seed/`
- Restarted `tradebot.service`

## Verification
Balances seeded; bot active. Fills still require expected edge ≳ fees (~0.45%+); watch diagnosis / receipts.

## Notes
Cash/alts no longer match Kraken screenshot (ETH qty still matches). 093 baseline can be restored again if needed.
