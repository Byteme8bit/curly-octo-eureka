"""Print the current paper portfolio snapshot file."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.paper_portfolio import PaperPortfolioLog  # noqa: E402


def main() -> int:
    from config import load_settings

    settings = load_settings()
    log = PaperPortfolioLog(settings.paper_portfolio_file)
    print(log.format_text(state_file=settings.state_file))
    return 0 if log.load() or settings.state_file.exists() else 1


if __name__ == "__main__":
    sys.exit(main())
