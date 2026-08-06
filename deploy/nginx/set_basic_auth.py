#!/usr/bin/env python3
"""Create nginx htpasswd + local creds file for TradeBot dashboard."""
from __future__ import annotations

import secrets
import subprocess
from pathlib import Path

USER = "sean"
PASS = secrets.token_urlsafe(16)
HTPASSWD = Path("/etc/nginx/.htpasswd-tradebot")
CREDS = Path("/home/cursor/eth-trading-bot/logs/.dashboard_basic_auth")

subprocess.check_call(
    ["sudo", "htpasswd", "-bBc", str(HTPASSWD), USER, PASS]
)
subprocess.check_call(["sudo", "chmod", "640", str(HTPASSWD)])
subprocess.check_call(["sudo", "chown", "root:www-data", str(HTPASSWD)])
CREDS.parent.mkdir(parents=True, exist_ok=True)
CREDS.write_text(f"{USER}\n{PASS}\n", encoding="utf-8")
CREDS.chmod(0o600)
subprocess.check_call(["sudo", "systemctl", "reload", "nginx"])
print(f"USER={USER}")
print(f"PASS={PASS}")
