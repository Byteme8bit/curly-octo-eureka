"""CLI: python -m bot.verifier [--last N] [--since DATE] [--json] [--html report.html]"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from bot.local_time import pacific_stamp
from bot.verifier.config import VerifierSettings
from bot.verifier.core import Verifier, format_pacific_now
from bot.verifier.report import format_text_report, write_html_report, write_json_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Independently verify TradeBot paper trades against receipts, logs, and Kraken public data.",
    )
    parser.add_argument("--last", type=int, default=None, help="Review only the last N trades")
    parser.add_argument("--since", type=str, default=None, help="Review trades since ISO date (YYYY-MM-DD)")
    parser.add_argument("--json", action="store_true", help="Also write JSON report to reports/")
    parser.add_argument("--html", type=str, default=None, metavar="PATH", help="Write HTML report to PATH")
    parser.add_argument("--verbose", "-v", action="store_true", help="Include all trades in text output")
    parser.add_argument("--skip-kraken", action="store_true", help="Skip live Kraken API checks")
    args = parser.parse_args(argv)

    settings = VerifierSettings.from_env()
    if args.skip_kraken:
        settings = replace(settings, skip_kraken=True)

    report = Verifier(settings).run(last=args.last, since=args.since)
    print(format_text_report(report, verbose=args.verbose))

    stamp = pacific_stamp()
    if args.json:
        json_path = settings.reports_dir / f"verification_{stamp}.json"
        write_json_report(report, json_path)
        print(f"\nJSON report: {json_path}")

    if args.html:
        html_path = write_html_report(report, Path(args.html))
        print(f"HTML report: {html_path}")

    return 0 if report.deny == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
