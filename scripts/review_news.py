"""Read-only crypto-news review for the maintenance automation.

The scheduled maintenance agent (see ``automation/maintenance_prompt.md``) is
expected to *review recent crypto news* every run and tie at least one of its
observations or improvements to what it finds here. This wraps the existing
``bot/auditor/news_client.NewsClient`` so the agent has one reliable command to
run instead of hand-rolling RSS parsing.

This script makes **no changes** — it only fetches and prints headlines. It
never raises on network failure (the underlying client degrades to [] / cache),
so it is safe to run unattended in the cloud sandbox.

Usage:
    python scripts/review_news.py
    python scripts/review_news.py --assets ETH,BTC,SOL --max 12
    python scripts/review_news.py --json

Exit code is always 0 (a quiet news day is not an error); it prints a short
``(no headlines)`` notice when nothing came back so the agent can record that.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Allow running as ``python scripts/review_news.py`` from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.auditor.news_client import NewsClient  # noqa: E402


DEFAULT_ASSETS = ("ETH", "BTC", "SOL", "XRP", "DOGE")


def _parse_assets(raw: str) -> list[str]:
    items = [a.strip().upper() for a in (raw or "").split(",")]
    return [a for a in items if a] or list(DEFAULT_ASSETS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--assets",
        default=",".join(DEFAULT_ASSETS),
        help="Comma-separated tickers to prioritise (default: ETH,BTC,SOL,XRP,DOGE).",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=10,
        help="Maximum number of headlines to print (default: 10).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of the text summary.",
    )
    args = parser.parse_args()

    assets = _parse_assets(args.assets)
    client = NewsClient()
    headlines = client.fetch_headlines(assets, max_items=max(1, args.max))

    if args.json:
        payload = [
            {
                "title": h.title,
                "url": h.url,
                "source": h.source,
                "published_at": h.published_at,
                "tickers": h.tickers,
                "sentiment": h.sentiment,
            }
            for h in headlines
        ]
        print(json.dumps({"assets": assets, "count": len(payload), "headlines": payload}, indent=2))
        return 0

    print(f"Crypto news review — prioritising {', '.join(assets)} (provider: {client.provider})")
    if not headlines:
        print("(no headlines — feeds empty or unreachable; record this and continue)")
        return 0

    for i, h in enumerate(headlines, 1):
        tickers = f" [{', '.join(h.tickers)}]" if h.tickers else ""
        when = f" — {h.published_at}" if h.published_at else ""
        print(f"{i:>2}. {h.title}{tickers}")
        print(f"    {h.source}{when}")
        if h.url:
            print(f"    {h.url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
