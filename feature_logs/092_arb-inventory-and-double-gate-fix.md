# 092 — Arb inventory rebalance + double-gate fix

**Requested:** 2026-08-06 23:00 PDT
**Status:** complete

## Request
Figure out why arb stopped after real fees; update tradebot on VPS.
Permission: rebalance paper + arb inventory on VPS.

## Root cause
1. Real ~0.40% fees correctly kill most triangular loops (need ~1.2%+ gross).
2. Paper book was ~70% ETH / dust ADA — stat-arb signals couldn't sell the overperformer.
3. Stat-arb edge used absolute ratio σ → always ~0 on pairs like ADA/ETH.
4. Engine passed **preflight net** into `approve_action`, which re-applied the **gross** fee hurdle → double-gate ("ready if approved" forever).

## Actions taken
- VPS paper rebalance from USD: ~$120 ADA, $80 BTC, $60 SOL, $40 LINK (ETH kept); archive under `archive/2026-08-07-arb-inventory-rebalance/`
- VPS `.env`: `STAT_ARB_ZSCORE_THRESHOLD=1.4`, `DUST_USD=15`, `PAPER_ANCHOR_TO_LIVE=0`, `MIN_TRADE_EDGE=0.0035`, `CRYPTO_MIN_TRADE_EDGE=0.0035`, `IDLE_REEVAL_MAX_ATTEMPTS=12`, `IDLE_REEVAL_HOURS=0.5` (fees still real)
- `bot/strategies/stat_arb.py` — relative σ edge (`|z| × σ/mean`)
- `bot/risk.py` + `bot/engine.py` — `edge_is_net=True` after preflight
- `tests/test_force_multihop_edge.py` — single-hop net not double-gated
- Deployed modules to VPS; restarted `tradebot.service`

## Verification
VPS after fix: multiple `stat_arb` fills (ADA→ETH, ADA→BTC). Run locally:
```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_stat_arb.py tests/test_force_multihop_edge.py -q
```

## Notes
Triangular still usually blocked under real taker fees — expected. Activity is mainly mean-reversion stat-arb.
