#!/usr/bin/env python3
import json
from pathlib import Path

p = Path("/home/cursor/eth-trading-bot/logs/trade_diagnosis.json")
d = json.loads(p.read_text(encoding="utf-8"))
print("decision", d.get("decision"))
print("thresholds", d.get("thresholds"))
print("blocked", (d.get("blocked") or [])[:4])
for op in (d.get("best_opportunities") or [])[:5]:
    print("op", op)
