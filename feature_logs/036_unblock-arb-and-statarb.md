# 036 — Unblock triangular arb and stat-arb signals

**Status:** awaiting verification - pytest pending

## Problem

Three independent bugs blocked every profitable trade in the paper bot:

1. `MIN_ETH_RESERVE=0.5` in `.env` equals the portfolio's entire ETH holding
   (0.5 ETH), so `clamp_eth_sell_size` returned 0 for every ETH-starting arb,
   and `validate_intent` rejected it.

2. For closed triangular-arb loops (ETH→UNI→AAVE→ETH), `from_asset == to_asset
   == "ETH"`.  The reserve check treated this as an open ETH *sell* and deducted
   the full position from the reserve — even though ETH is only an intermediate
   that is returned atomically at loop end.

3. `StatArbStrategy` used `gross = abs(z) * 0.001` as an edge proxy.  At
   z=1.9 this gives 0.0019, which is *below* the 0.002 `MIN_NET_PROFIT_PCT`
   gate.  Real signals were discarded not because the opportunity was bad, but
   because the formula was an arbitrary placeholder.

## Changes

### Fix 1 — `MIN_ETH_RESERVE` in `.env`

```
Before: MIN_ETH_RESERVE=0.5
After:  MIN_ETH_RESERVE=0.25
```

`.env` is gitignored and edited directly — not committed.

### Fix 2 — Closed-loop ETH exemption (`bot/portfolio_constraints.py`)

`validate_intent` now detects `is_closed_loop = (intent.from_asset == intent.to_asset)`.  
When true, `clamp_eth_sell_size` is skipped entirely (ETH net balance is unchanged
after the loop) and the `size_pct <= 0` error path is skipped.  
Open ETH sells (`from_asset = "ETH"`, `to_asset ≠ "ETH"`) are unaffected.

### Fix 3 — Stat-arb edge formula (`bot/strategies/stat_arb.py`)

```python
# Before
gross = abs(z) * 0.001  # expected reversion edge proxy

# After
sigma_ratio = float(ratio.std()) if len(ratio) >= 10 else 0.0
gross = min(abs(z) * sigma_ratio, 0.05)
```

A z-score deviation of `z` standard deviations implies an expected mean-reversion
move of `z × σ_ratio` in ratio units ≈ gross return.  At typical crypto pair
volatility (σ_ratio ≈ 0.005–0.05), z=1.5 produces gross ≈ 0.008–0.075, safely
above the 0.002 `MIN_NET_PROFIT_PCT` gate.  The 5 % cap prevents implausibly large
estimates on thin pairs.

## Tests added

- `tests/test_portfolio_constraints.py` — two new cases:
  - `test_closed_loop_eth_exempted_from_reserve_check`: ETH at/below reserve, closed
    loop must still be allowed.
  - `test_open_eth_sell_still_blocked_at_reserve`: open ETH→UNI sell at the same
    balance must be rejected (no regression).

- `tests/test_stat_arb.py` (new file):
  - `test_stat_arb_edge_above_gate_at_z1_5`: z=1.5 with realistic σ gives edge above
    MIN_NET_PROFIT_PCT.
  - `test_stat_arb_edge_capped_at_max`: extremely high z or σ never exceeds 0.05.
  - `test_stat_arb_below_threshold_no_intent`: z below threshold emits nothing.
  - `test_stat_arb_insufficient_holding_blocked`: insufficient from_asset holding is
    still blocked.

## Verification commands

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q
```

Expected: 323+ tests passing (319 existing + 4 new).
