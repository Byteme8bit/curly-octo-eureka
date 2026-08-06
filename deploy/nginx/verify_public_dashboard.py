#!/usr/bin/env python3
from pathlib import Path
import subprocess

auth = Path("/home/cursor/eth-trading-bot/logs/.dashboard_basic_auth")
user, password = auth.read_text(encoding="utf-8").splitlines()[:2]
print(f"USER={user}")
print(f"PASS={password}")
for label, url in [
    ("page", "https://lynch.gdn/tradebot/"),
    ("api", "https://lynch.gdn/tradebot/api/paper/status"),
]:
    r = subprocess.run(
        ["curl", "-s", "-o", "/tmp/tbcheck.out", "-w", "%{http_code}", "-u", f"{user}:{password}", url],
        capture_output=True,
        text=True,
    )
    print(f"{label}_http={r.stdout.strip()}")
print(Path("/tmp/tbcheck.out").read_text(encoding="utf-8", errors="replace")[:180])
