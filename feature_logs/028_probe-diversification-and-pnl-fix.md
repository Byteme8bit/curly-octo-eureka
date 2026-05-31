# 028 — Probe diversification + cross-coin PnL accuracy fix

**Requested:** 2026-05-30
**Status:** verified in isolated worktree — 274 pytest passing; live `.env` retune recommended (see below)
**Base branch:** stacked on `feat/day-trader-probe-and-forced-trading` (PR #17)

## Request
> Tune the bot so it actively and frequently makes paper trades — diversifying,
> doing cross-coin rotations, mitigating losses — while considering news. Run it
> in an isolated worktree (the live bot must not be disturbed), iterate
> run→observe→tweak→run, then hand back the exact live `.env` values.

## Method
All runs were done in a throwaway git worktree (`eth-trading-bot-tune`) based on
`feat/day-trader-probe-and-forced-trading` (08c03e5), with a test `.env`
(`DISCORD_ENABLED=0`, `ALERTS_ENABLED=0`, `RESET_PAPER_STATE=1`, no secrets,
`POLL_INTERVAL=5`, `IDLE_PROBE_FORCE_MINUTES=1` for fast observation). Kraken
public market data only. Each run was time-boxed to ~2–4 min and the process
killed afterward.

## Findings
1. **Forced probe path works** — with `IDLE_PROBE_FORCE_MINUTES=1` a probe fired
   roughly once a minute, so the bot is never silent.
2. **Genuine strategy trades are correctly blocked** in a flat tape: observed
   momentum/rotation edges were ~+0.0010–0.0017 while one Kraken taker leg is
   0.26% and a round trip ~0.52%. Pre-flight correctly rejects (e.g. the
   ETH→UNI→BTC→ETH triangular cycle shows gross +0.0017 but needs ~0.78% to clear
   three legs). So in calm markets the **probe is the only thing that can trade
   frequently** — honest, expected behaviour.
3. **Bug: phantom loss on every buy into a new coin.** `_execute_leg`'s cross-pair
   BUY computed `gain_loss = to_usd - from_usd`, valuing the *received* asset at
   `usd_prices[base]`. The engine only fetches USD prices for assets already held,
   so a buy into an un-held coin used a $0 price → a fake loss equal to the whole
   notional (e.g. a $101 probe reported **−$101.47**). Next tick re-priced it and
   the portfolio recovered, but receipts, the strategy governor's reward signal,
   and Discord trade alerts all saw a bogus six-figure-bps loss.
4. **Probe didn't diversify** — it always re-bought the single intent the strategy
   emitted (UNI), pushing UNI from 5%→14% over three probes, and it bypassed the
   ETH-reserve / alt-cap guards entirely.

## What changed (code)

### 1. `bot/paper_broker.py` — accurate conversion PnL
When the bought asset has no USD reference price, value it from the post-fee quote
converted instead of $0. A conversion's immediate realized PnL is then just the
fee paid, not a phantom loss of the notional.

### 2. `bot/engine.py` — diversifying, reserve-safe probe
- `_pick_probe_candidate` now searches **intents *and* opportunities together**
  and prefers a destination coin we do **not** already hold, so a string of
  probes rotates across coins (verified: UNI → ATOM → DOT on consecutive probes).
- New `_probe_respects_eth_reserve` guard: a probe can never sell ETH below
  `MIN_ETH_RESERVE` (the probe bypasses the normal constraint pipeline, so the
  reserve floor is re-applied here).
- Fallbacks now diversify spare USD into an un-held core coin / trim the largest
  over-reserve holding to USD.

## Evidence (isolated run, fixes applied)
Three consecutive forced probes diversified into three different coins, each with
correct fee-only PnL (no phantom loss):
```
Traded 0.0500 ETH -> 33.40 UNI  | Fee $0.26 | Gain/Loss -$0.26
Traded 0.0475 ETH -> 48.05 ATOM | Fee $0.25 | Gain/Loss -$0.25
Traded 0.0451 ETH -> 76.94 DOT  | Fee $0.24 | Gain/Loss -$0.24
```
Resulting portfolio spanned 5 assets (ADA, ATOM, DOT, ETH, UNI), Total $2,047.15
(PnL +$0.22), ETH 0.857 (safely above the 0.25 reserve). News client returned
8 live headlines (CoinDesk / Cointelegraph) via `rss,coingecko`.

## Files changed
- **Modified** `bot/paper_broker.py` — conversion-PnL fallback when base USD price missing.
- **Modified** `bot/engine.py` — diversifying + ETH-reserve-safe probe selection.
- **New** `feature_logs/028_probe-diversification-and-pnl-fix.md` (this file).

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest -q          # 274 passing
```

## Recommended LIVE `.env` (replace the test-only extremes)
```
DAY_TRADER_MODE=1
FEE_FORCE_STATIC=1
FEE_RATE=0.0026
MIN_TRADE_EDGE=0.002
FEE_SAFETY_MULTIPLIER=1.1
MIN_NET_PROFIT_PCT=0.0005
STAT_ARB_ZSCORE_THRESHOLD=1.5
POLL_INTERVAL=15
IDLE_PROBE_FORCE_MINUTES=20      # NOT the test value of 1
IDLE_PROBE_SIZE_PCT=0.05
MIN_ETH_RESERVE=0.25
MAX_ALT_ALLOCATION_PCT=0.40
TRADE_COOLDOWN_SECONDS=45
MAX_TRADES_PER_HOUR=40
```

## Honest caveats
- Frequent, varied activity is guaranteed; **profitability is not** — it is
  market-dependent. In flat tape most fills are probes that pay fees.
- `FEE_FORCE_STATIC=1` assumes 0.26% while real Kraken taker is ~0.40%. Fine for
  paper; before any real-money use, set `FEE_FORCE_STATIC=0` and raise
  `MIN_TRADE_EDGE`.
- A probe deliberately ignores the edge/fee gate (it can lose a fee on purpose to
  stay active). It now respects the ETH reserve and diversifies, but it is still a
  "stay active" valve, not an alpha source.
