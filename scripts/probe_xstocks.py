"""One-shot probe: which xStock USD pairs are online on Kraken for this region."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from bot.equities import (  # noqa: E402
    equity_usd_symbol,
    fetch_equity_ticker,
    fetch_tokenized_pairs,
    kraken_pair_id,
    list_online_usd_equities,
)

CANDIDATES = ("AAPLx", "TSLAx", "SPYx", "NVDAx", "MSFTx", "GOOGLx", "AMDx")
OUT = ROOT / "logs" / "xstocks_probe.json"


def main() -> int:
    probe: dict = {
        "probed_at": datetime.now(timezone.utc).isoformat(),
        "api": "Kraken public AssetPairs?aclass_base=tokenized_asset",
        "has_api_keys": bool(os.getenv("KRAKEN_API_KEY") and os.getenv("KRAKEN_API_SECRET")),
        "catalog_size": 0,
        "online_usd_unique": 0,
        "geo_block_hint": None,
        "symbols": [],
        "validated": [],
        "amd_symbol": None,
        "nvda_symbol": None,
    }

    try:
        pairs = fetch_tokenized_pairs()
        probe["catalog_size"] = len(pairs)
        online = list_online_usd_equities(pairs)
        probe["online_usd_unique"] = len(online)
        probe["online_usd_tickers"] = list(online)
        amd = [t for t in online if "AMD" in t.upper()]
        nvda = [t for t in online if "NVDA" in t.upper()]
        probe["amd_symbol"] = amd[0] if amd else None
        probe["nvda_symbol"] = nvda[0] if nvda else None
    except Exception as exc:
        probe["error"] = str(exc)
        probe["geo_block_hint"] = (
            "AssetPairs fetch failed — possible geo block or API outage"
        )
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(probe, indent=2), encoding="utf-8")
        print(json.dumps(probe, indent=2))
        return 1

    if probe["catalog_size"] == 0:
        probe["geo_block_hint"] = (
            "Empty tokenized_asset catalog — likely geo-restricted (USA) or unavailable region"
        )

    by_ws: dict[str, dict] = {}
    by_base: dict[str, dict] = {}
    for info in pairs.values():
        ws = str(info.get("wsname") or "")
        base = str(info.get("base") or "")
        if ws:
            by_ws[ws.upper()] = info
        if base:
            by_base[base.upper()] = info

    for asset in CANDIDATES:
        symbol = equity_usd_symbol(asset)
        pair_id = kraken_pair_id(symbol)
        info = by_ws.get(symbol.upper()) or by_base.get(asset.upper())
        row: dict = {
            "symbol": asset,
            "pair": symbol,
            "pair_id": pair_id,
            "tradable": False,
            "status": None,
            "ticker_ok": False,
            "ticker_error": None,
        }
        if info:
            row["status"] = str(info.get("status", ""))
            for pid, pinfo in pairs.items():
                if pinfo is info:
                    row["kraken_pair_key"] = pid
                    row["pair_id"] = pid
                    break
            online = str(info.get("status", "online")) == "online"
            if online:
                try:
                    price = fetch_equity_ticker(symbol)
                    row["ticker_ok"] = True
                    row["last_price"] = price
                    row["tradable"] = True
                except Exception as te:
                    row["ticker_error"] = str(te)
        probe["symbols"].append(row)
        if row["tradable"]:
            probe["validated"].append(asset)

    probe["validated_pairs"] = [equity_usd_symbol(a) for a in probe["validated"]]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(probe, indent=2), encoding="utf-8")

    print(f"CATALOG_SIZE {probe['catalog_size']}")
    print(f"ONLINE_USD_UNIQUE {probe.get('online_usd_unique', 0)}")
    if probe.get("amd_symbol"):
        print(f"AMD_SYMBOL {probe['amd_symbol']}")
    if probe.get("nvda_symbol"):
        print(f"NVDA_SYMBOL {probe['nvda_symbol']}")
    validated = probe["validated"]
    print(f"VALIDATED {','.join(validated) if validated else '(none)'}")
    for r in probe["symbols"]:
        print(
            f"{r['symbol']:8} pair={r['pair']:12} status={r['status']} "
            f"tradable={r['tradable']} ticker_ok={r['ticker_ok']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
