# 093 — Restore Kraken screenshot baseline

**Requested:** 2026-08-06 23:38 PDT
**Status:** complete

## Request
Confirm paper balances match the prior Kraken portfolio screenshot; if not, make them match and update.

## Actions taken
- Confirmed VPS had drifted (BTC/SOL/LINK + post-092 trades) away from `paper_baseline.json` (`source: kraken_screenshot_manual`)
- Archived prior state → `archive/2026-08-07-restore-screenshot-baseline/`
- Restored balances exactly:
  - ETH `0.52042`, USD `415.90`, ADA `24.602263`, KFEE `881.92`
- Cleared paper trades; reset goals session markers to `$1,397.51`
- Set `INITIAL_BALANCES` to match; restarted `tradebot.service`
- Kept 092 code fixes (relative-σ edge, `edge_is_net`); inventory rebalance intentionally undone

## Verification
VPS `.paper_state.json` balances match `paper_baseline.json`; `n_trades=0`.
