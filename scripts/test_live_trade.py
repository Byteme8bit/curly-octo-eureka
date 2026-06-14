"""One-shot live Kraken test sell — run manually, not part of the bot loop."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.data import KrakenData
from bot.live_broker import LiveBroker
from bot.markets import PairInfo
from bot.strategies.base import Signal
from config import load_settings


def main() -> int:
    settings = load_settings()
    if not settings.api_key or not settings.api_secret:
        print("FAIL: KRAKEN_API_KEY / KRAKEN_API_SECRET missing in .env")
        return 1

    data = KrakenData(settings)
    broker = LiveBroker(
        exchange=data.exchange,
        fee_rate=settings.fee_rate,
        state_file=ROOT / ".live_state.json",
        min_usd_trade=settings.min_usd_trade,
        max_usd_per_trade=25.0,
        reset=False,
    )

    price = float(data.fetch_ticker("ETH/USD"))
    usd_prices = {"ETH": price, "USD": 1.0}
    eth_before = broker.balance("ETH")
    usd_before = broker.balance("USD")
    target_usd = 18.0
    size_pct = min(0.05, target_usd / max(eth_before * price, 1.0))

    print(f"Pre-trade  ETH={eth_before:.6f}  USD={usd_before:.2f}  ETH/USD={price:.2f}")
    print(f"Test sell  size_pct={size_pct:.4f}  (~${size_pct * eth_before * price:.2f})")

    pair = PairInfo(symbol="ETH/USD", base="ETH", quote="USD")
    trade = broker.execute(
        pair,
        Signal.SELL,
        price,
        usd_prices,
        reason="manual live connectivity test",
        size_pct=size_pct,
    )
    if not trade:
        print("FAIL: LiveBroker.execute returned None")
        return 1

    broker.sync_from_exchange()
    receipt = ROOT / "receipts" / f"live-test-{trade.get('order_id', 'unknown')}.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(trade, indent=2), encoding="utf-8")

    print("SUCCESS — live market order filled")
    print("order_id:", trade.get("order_id"))
    print("sold ETH:", trade.get("from_qty"))
    print("received USD:", trade.get("to_qty"))
    print("fee USD:", round(float(trade.get("fee_usd") or 0), 4))
    print(f"Post-trade ETH={broker.balance('ETH'):.6f}  USD={broker.balance('USD'):.2f}")
    print("receipt:", receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
