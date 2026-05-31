# 026 — Roll back the fee wall + guaranteed hail-mary probe

**Requested:** 2026-05-30
**Status:** awaiting verification — pytest passing locally (274), live restart pending

## Request
> The bot is doing NOTHING and I don't trust it. Roll back to when it was
> actively coin-to-coin trading — I think a fee discrepancy change killed it
> ("you said the fees are actually THIS"). And the idle hail-mary: I DON'T care
> if it loses money, this is paper. I'd rather see action than the same thing
> over and over. Also there's a Discord 503 error in the terminal. FIX IT.

## Diagnosis (from the screenshot + code)
- Bot was healthy: `Total $2,051.95 (PnL +18.39)`, fetching every ~8s.
- Stuck "need +0.0053 more edge" — the best opportunity was below the edge bar.
- Root cause confirmed: `FeeEngine` pulls **live** Kraken taker fees (~0.40%,
  up from 0.26%); `PreFlightValidator` uses those for its net-profit gate, so
  in calm markets nothing clears. Plus req 024 raised `MIN_TRADE_EDGE` to 0.006.
- The `503 Service Unavailable` was a transient Discord API hiccup in the command
  poller — caught and non-fatal, but it logged a full traceback + posted an alert.

## What changed

### 1. Fee rollback switch (`bot/fee_engine.py`, `config.py`, `bot/engine.py`)
New `FeeEngine(force_static=...)` — when on, ignores Kraken's live schedule and
uses the env `FEE_RATE` for every pair (and never calls the exchange). Wired to
`FEE_FORCE_STATIC` env. This is the literal "use the old assumed fee" rollback.

### 2. Guaranteed hail-mary probe (`bot/engine.py`, `config.py`)
New `idle_probe_force_minutes` / `idle_probe_size_pct`. If nothing trades for
that many minutes, `_maybe_force_probe` executes ONE small trade that **bypasses
the edge/fee/preflight gates** (picks the top blocked intent, else a considered
opportunity, else sells a sliver of the largest holding to USD / buys a little
ETH). It posts a clear "🃏 Forced probe trade" message. A monotonic guard +
idle reset prevent spamming (≈ one probe per idle window). Paper-only; may lose
fees by design — exactly what the user asked for.

### 3. Quieter Discord transient errors (`bot/discord_bot.py`)
`_poll_loop` now recognizes transient upstream errors (429/5xx/Service
Unavailable/connection reset/timeout), logs a one-line warning instead of a
traceback, and only escalates to a Discord alert after 15 consecutive failures.

### 4. `.env` retune (gitignored)
`FEE_FORCE_STATIC=1`, `FEE_RATE=0.004→0.0026`, `MIN_TRADE_EDGE=0.006→0.0015`,
`FEE_SAFETY_MULTIPLIER=2.0→1.0`, `IDLE_PROBE_FORCE_MINUTES=15`,
`IDLE_PROBE_SIZE_PCT=0.05`.

## Files changed
- **Modified** `bot/fee_engine.py` — `force_static` override.
- **Modified** `bot/engine.py` — `_maybe_force_probe`, `_pick_probe_candidate`, FeeEngine wiring.
- **Modified** `bot/discord_bot.py` — transient-error handling in `_poll_loop`.
- **Modified** `config.py` — `idle_probe_force_minutes`, `idle_probe_size_pct`, `fee_force_static`.
- **Modified** `tests/test_fee_engine.py` — 2 tests for the static override.
- **Modified** `.env` (gitignored) — retune above.

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest -q                 # 274 passing
.\.venv\Scripts\python.exe .\scripts\verify_main_startup.py
```
Live: restart the bot. Expect (a) far more coin-to-coin trades (live-fee wall
removed), and (b) at worst, a forced probe trade every ~15 min so it is never
silent. Each fill posts the new `Why:` rationale.

## Honest note
With `FEE_FORCE_STATIC=1` + thin edge bar, simulated fills assume 0.26% fees
while real Kraken is ~0.40%; on paper that is fine and gives activity, but these
numbers would be optimistic on a live account. Flip `FEE_FORCE_STATIC=0` and
raise `MIN_TRADE_EDGE` before ever going real.
