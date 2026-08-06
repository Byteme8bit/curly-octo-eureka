#!/usr/bin/env python3
"""Insert tradebot dashboard nginx include into lynch.gdn HTTPS server."""
from pathlib import Path

p = Path("/etc/nginx/sites-enabled/default")
text = p.read_text(encoding="utf-8")
if "snippets/tradebot-dashboard.conf" in text:
    print("already included")
    raise SystemExit(0)
needle = "include /etc/nginx/snippets/security-headers.conf;"
if needle not in text:
    raise SystemExit("security-headers include not found in default site")
insert = needle + "\n\n    include /etc/nginx/snippets/tradebot-dashboard.conf;"
p.write_text(text.replace(needle, insert, 1), encoding="utf-8")
print("nginx include added")
