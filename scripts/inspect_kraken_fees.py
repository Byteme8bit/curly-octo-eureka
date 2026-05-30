"""One-shot diagnostic: dump Kraken's fee structure for the pairs we trade.

Run: python scripts/inspect_kraken_fees.py

Prints what ccxt returns for `market['taker']`, `market['maker']`, AND the raw
`market['info']` so we can see where the 0.40% number is coming from.
"""

from __future__ import annotations

import json
import ccxt

PAIRS = ["ETH/USD", "BTC/USD", "SOL/USD", "ADA/USD", "USDC/USDT", "ETH/BTC"]


def main() -> None:
    ex = ccxt.kraken({"enableRateLimit": True})
    print(f"ccxt version: {ccxt.__version__}\n")

    print("Loading markets from Kraken (public, no auth)...")
    markets = ex.load_markets()
    print(f"Loaded {len(markets)} markets.\n")

    print("Exchange-level defaults from ex.fees['trading']:")
    print(f"  {ex.fees.get('trading', {})}\n")

    for sym in PAIRS:
        m = markets.get(sym)
        if not m:
            print(f"{sym:12} NOT FOUND")
            continue
        taker = m.get("taker")
        maker = m.get("maker")
        tier_based = m.get("tierBased")
        info = m.get("info", {})
        # Kraken's raw 'fees' tier ladder lives in info['fees'] / info['fees_maker']
        raw_fees = info.get("fees")
        raw_fees_maker = info.get("fees_maker")
        print(f"{sym:12} taker={taker!s:8}  maker={maker!s:8}  tierBased={tier_based}")
        print(f"             raw 'fees'        = {raw_fees}")
        print(f"             raw 'fees_maker'  = {raw_fees_maker}")
        print()


if __name__ == "__main__":
    main()
