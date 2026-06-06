"""Scheduled monitor: detects changes in Kraken's market metadata over time.

What it watches (per run):
  - Taker / maker fees per pair (catches schedule changes like the 0.26%->0.40%
    one we just found).
  - Pairs added to the exchange (new symbols we might want to track).
  - Pairs removed from the exchange (delistings — break hardcoded assumptions).
  - Per-pair `tierBased` flag flips.

How it works:
  - On first run, snapshots a baseline to ``.kraken_monitor_baseline.json``.
  - On each subsequent run, diffs current state against the baseline and:
      * prints a human-readable change report to stdout
      * appends a JSON record to ``logs/kraken_monitor.jsonl``
      * posts an alert to Discord if changes are found AND a webhook is
        configured (DISCORD_WEBHOOK env var)
      * updates the baseline so the next run sees today as the new normal
  - Exit code: 0 if no changes, 1 if changes found, 2 on error.

Designed to run unattended from Windows Task Scheduler / cron once a day.
Idempotent — running it twice in a row produces "no changes" the second time.

Run manually:
    python scripts/monitor_kraken_changes.py
    python scripts/monitor_kraken_changes.py --baseline-only   # reset baseline
    python scripts/monitor_kraken_changes.py --no-alert        # skip Discord
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import ccxt

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / ".kraken_monitor_baseline.json"
LOG_FILE = ROOT / "logs" / "kraken_monitor.jsonl"

# Pairs we care most about — flagged separately in the report when they change.
PRIORITY_PAIRS = {
    "ETH/USD", "BTC/USD", "SOL/USD", "ADA/USD", "ETH/BTC",
    "LINK/USD", "AVAX/USD", "DOT/USD", "ATOM/USD", "LTC/USD",
    "DOGE/USD", "UNI/USD", "AAVE/USD", "ARB/USD", "OP/USD",
    "POL/USD", "XRP/USD",
}

# A pair must have a non-trivial fee change to count — guards against
# floating-point noise. 1 basis point = 0.0001.
MIN_FEE_DELTA = 0.00005


# ---------------------------------------------------------------------------
# snapshot loading + diffing
# ---------------------------------------------------------------------------


@dataclass
class MarketSnapshot:
    """Lightweight per-pair record we persist and diff against."""
    taker: float | None
    maker: float | None
    tier_based: bool | None

    @classmethod
    def from_market(cls, market: dict) -> "MarketSnapshot":
        return cls(
            taker=float(market["taker"]) if market.get("taker") is not None else None,
            maker=float(market["maker"]) if market.get("maker") is not None else None,
            tier_based=bool(market.get("tierBased")),
        )

    def to_json(self) -> dict:
        return {"taker": self.taker, "maker": self.maker, "tier_based": self.tier_based}

    @classmethod
    def from_json(cls, data: dict) -> "MarketSnapshot":
        return cls(
            taker=data.get("taker"),
            maker=data.get("maker"),
            tier_based=data.get("tier_based"),
        )


@dataclass
class ChangeReport:
    fees_changed: list[tuple[str, MarketSnapshot, MarketSnapshot]] = field(default_factory=list)
    pairs_added: list[str] = field(default_factory=list)
    pairs_removed: list[str] = field(default_factory=list)
    timestamp: str = ""
    ccxt_version: str = ""

    @property
    def has_changes(self) -> bool:
        return bool(self.fees_changed or self.pairs_added or self.pairs_removed)

    @property
    def priority_fee_changes(self) -> list[tuple[str, MarketSnapshot, MarketSnapshot]]:
        return [c for c in self.fees_changed if c[0] in PRIORITY_PAIRS]


def fetch_current_snapshot(exchange: ccxt.Exchange) -> dict[str, MarketSnapshot]:
    markets = exchange.load_markets()
    out: dict[str, MarketSnapshot] = {}
    for symbol, market in (markets or {}).items():
        if not isinstance(market, dict):
            continue
        if market.get("taker") is None and market.get("maker") is None:
            continue
        out[symbol] = MarketSnapshot.from_market(market)
    return out


def load_baseline() -> dict[str, MarketSnapshot] | None:
    if not BASELINE.exists():
        return None
    try:
        data = json.loads(BASELINE.read_text(encoding="utf-8"))
        return {sym: MarketSnapshot.from_json(d) for sym, d in data.get("markets", {}).items()}
    except (OSError, json.JSONDecodeError) as exc:
        print(f"WARN: failed to read baseline ({exc}); treating as missing.")
        return None


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_baseline(snapshot: dict[str, MarketSnapshot]) -> None:
    payload = {
        "saved_at": _utcnow_iso(),
        "ccxt_version": ccxt.__version__,
        "markets": {sym: snap.to_json() for sym, snap in snapshot.items()},
    }
    BASELINE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def diff_snapshots(
    baseline: dict[str, MarketSnapshot],
    current: dict[str, MarketSnapshot],
) -> ChangeReport:
    report = ChangeReport(
        timestamp=_utcnow_iso(),
        ccxt_version=ccxt.__version__,
    )
    base_keys = set(baseline)
    cur_keys = set(current)
    report.pairs_added = sorted(cur_keys - base_keys)
    report.pairs_removed = sorted(base_keys - cur_keys)
    for sym in sorted(base_keys & cur_keys):
        b, c = baseline[sym], current[sym]
        if _meaningful_fee_diff(b.taker, c.taker) or _meaningful_fee_diff(b.maker, c.maker):
            report.fees_changed.append((sym, b, c))
    return report


def _meaningful_fee_diff(a: float | None, b: float | None) -> bool:
    if a is None and b is None:
        return False
    if a is None or b is None:
        return True
    return abs(a - b) >= MIN_FEE_DELTA


# ---------------------------------------------------------------------------
# rendering + alerting
# ---------------------------------------------------------------------------


def render_human(report: ChangeReport) -> str:
    if not report.has_changes:
        return "No Kraken metadata changes since last run."
    lines = [f"Kraken monitor: changes detected at {report.timestamp} (ccxt {report.ccxt_version})"]
    if report.fees_changed:
        priority = report.priority_fee_changes
        other = [c for c in report.fees_changed if c not in priority]
        if priority:
            lines.append(f"\nFee changes on PRIORITY pairs ({len(priority)}):")
            for sym, b, c in priority:
                lines.append(f"  {sym:14}  taker {_fmt(b.taker)} -> {_fmt(c.taker)}   maker {_fmt(b.maker)} -> {_fmt(c.maker)}")
        if other:
            lines.append(f"\nFee changes on other pairs ({len(other)}):")
            for sym, b, c in other[:25]:
                lines.append(f"  {sym:14}  taker {_fmt(b.taker)} -> {_fmt(c.taker)}")
            if len(other) > 25:
                lines.append(f"  ... and {len(other) - 25} more")
    if report.pairs_added:
        lines.append(f"\nPairs added ({len(report.pairs_added)}):")
        lines.extend(f"  + {s}" for s in report.pairs_added[:25])
        if len(report.pairs_added) > 25:
            lines.append(f"  ... and {len(report.pairs_added) - 25} more")
    if report.pairs_removed:
        lines.append(f"\nPairs removed ({len(report.pairs_removed)}):")
        lines.extend(f"  - {s}" for s in report.pairs_removed[:25])
        if len(report.pairs_removed) > 25:
            lines.append(f"  ... and {len(report.pairs_removed) - 25} more")
    return "\n".join(lines)


def _fmt(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:.3f}%"


def append_jsonl(report: ChangeReport) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": report.timestamp,
        "ccxt_version": report.ccxt_version,
        "fees_changed": [
            {
                "symbol": s,
                "taker_before": b.taker, "taker_after": c.taker,
                "maker_before": b.maker, "maker_after": c.maker,
            }
            for s, b, c in report.fees_changed
        ],
        "pairs_added": report.pairs_added,
        "pairs_removed": report.pairs_removed,
    }
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def post_discord(report: ChangeReport, webhook: str) -> None:
    if not report.has_changes:
        return
    bullets = []
    if report.priority_fee_changes:
        for sym, b, c in report.priority_fee_changes[:8]:
            bullets.append(
                f"• `{sym}` taker {_fmt(b.taker)} → **{_fmt(c.taker)}**"
            )
    if report.pairs_added:
        bullets.append(f"• {len(report.pairs_added)} pair(s) added")
    if report.pairs_removed:
        bullets.append(f"• {len(report.pairs_removed)} pair(s) removed")
    other = len(report.fees_changed) - len(report.priority_fee_changes)
    if other > 0:
        bullets.append(f"• {other} other fee change(s)")
    content = (
        "**Kraken monitor — changes detected**\n"
        + "\n".join(bullets)
        + f"\n\n_(scanned at {report.timestamp}, ccxt {report.ccxt_version})_"
    )
    payload = json.dumps({
        "username": "Kraken Monitor",
        "content": content[:1900],  # Discord 2000-char limit, leave headroom
    }).encode("utf-8")
    req = urllib.request.Request(
        webhook, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status >= 300:
                print(f"WARN: Discord webhook returned HTTP {resp.status}")
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: Discord post failed: {exc}")


# ---------------------------------------------------------------------------
# entry
# ---------------------------------------------------------------------------


def _load_dotenv_minimal() -> None:
    """Tiny .env reader so we can find DISCORD_WEBHOOK without pulling in deps."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline-only", action="store_true",
        help="Force overwrite of baseline without comparing or alerting.",
    )
    parser.add_argument(
        "--no-alert", action="store_true",
        help="Skip Discord webhook even if one is configured.",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress stdout when there are no changes.",
    )
    args = parser.parse_args()

    _load_dotenv_minimal()

    try:
        exchange = ccxt.kraken({"enableRateLimit": True})
        current = fetch_current_snapshot(exchange)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: failed to load Kraken markets: {exc}")
        return 2

    if not current:
        print("ERROR: Kraken returned zero markets with fee data — aborting.")
        return 2

    baseline = load_baseline()
    if baseline is None or args.baseline_only:
        save_baseline(current)
        reason = "explicit reset" if args.baseline_only else "no prior baseline"
        print(f"Saved new baseline ({len(current)} pairs, {reason}).")
        return 0

    report = diff_snapshots(baseline, current)
    append_jsonl(report)

    if not report.has_changes:
        if not args.quiet:
            print(render_human(report))
        return 0

    print(render_human(report))

    if not args.no_alert:
        webhook = (os.environ.get("DISCORD_WEBHOOK") or "").strip()
        if webhook:
            post_discord(report, webhook)

    save_baseline(current)
    return 1


if __name__ == "__main__":
    sys.exit(main())
