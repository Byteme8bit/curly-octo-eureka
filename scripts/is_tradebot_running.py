"""Exit 0 when tradebot.lock points at a live process; otherwise exit 1.

Used by ``start_tradebot.ps1`` so pre-flight checks match ``bot.singleton``
PID semantics (including Windows OpenProcess liveness).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.singleton import LOCK_FILE, _pid_is_running  # noqa: E402


def tradebot_is_running() -> bool:
    """Return True when the singleton lock file references a live PID."""
    if not LOCK_FILE.exists():
        return False
    try:
        pid = int(LOCK_FILE.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return False
    return _pid_is_running(pid)


def main() -> int:
    return 0 if tradebot_is_running() else 1


if __name__ == "__main__":
    raise SystemExit(main())
