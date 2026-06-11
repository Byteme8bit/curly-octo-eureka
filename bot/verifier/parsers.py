"""Load trades and correlate receipts / logs."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bot.trade_log import format_qty
from watchdog.parsers import load_paper_state, parse_receipt

_RECEIPT_TIME = re.compile(r"^Time:\s+(.+)$", re.MULTILINE)
_TRADED_LINE = re.compile(r"^Traded (.+)$", re.MULTILINE)


def load_trades(state_file: Path) -> list[dict]:
    data = load_paper_state(state_file)
    if not data:
        return []
    return list(data.get("trades", []))


def load_initial_balances(state_file: Path) -> dict[str, float]:
    data = load_paper_state(state_file)
    if not data or "balances" not in data:
        return {}
    return {k: float(v) for k, v in data["balances"].items()}


def receipt_path_for_trade(trade: dict, receipts_dir: Path) -> Path | None:
    recorded = trade.get("receipt_file")
    if recorded:
        path = Path(recorded)
        if path.exists():
            return path
        # State may store absolute path; try basename under receipts_dir.
        candidate = receipts_dir / path.name
        if candidate.exists():
            return candidate

    from_a = trade.get("from_asset", "")
    to_a = trade.get("to_asset", "")
    if not from_a or not to_a:
        return None

    pattern = f"*-{from_a}-to-{to_a}.txt"
    matches = sorted(receipts_dir.glob(pattern), reverse=True)
    trade_time = _parse_iso(trade.get("time", ""))
    if trade_time and matches:
        best: Path | None = None
        best_delta = timedelta(days=9999)
        for path in matches:
            receipt_time = _receipt_timestamp(path)
            if receipt_time is None:
                continue
            delta = abs(receipt_time - trade_time)
            if delta < best_delta:
                best_delta = delta
                best = path
        if best and best_delta <= timedelta(hours=2):
            return best
    return matches[0] if matches else None


def _receipt_timestamp(path: Path) -> datetime | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = _RECEIPT_TIME.search(text)
    if m:
        return _parse_pacific_or_iso(m.group(1).strip())
    # Filename stamp: YYYYMMDD-HHMMSS
    stem = path.stem.split("-")[0:2]
    if len(stem) >= 2:
        try:
            return datetime.strptime("".join(stem), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_pacific_or_iso(value: str) -> datetime | None:
    parsed = _parse_iso(value)
    if parsed:
        return parsed
    for fmt in ("%Y-%m-%d %H:%M:%S %Z", "%Y-%m-%d %H:%M:%S PDT", "%Y-%m-%d %H:%M:%S PST"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def trade_narrative_snippet(trade: dict) -> str:
    from_a = trade["from_asset"]
    to_a = trade["to_asset"]
    from_qty = trade.get("from_qty", 0)
    to_qty = trade.get("to_qty", 0)
    return (
        f"Traded {format_qty(from_a, from_qty)} to {format_qty(to_a, to_qty)}"
    )


def find_log_mention(
    trade: dict,
    log_dir: Path,
    *,
    window_minutes: int = 30,
) -> tuple[bool, str]:
    """Return (found, detail) by scanning window logs and bot.log."""
    trade_time = _parse_iso(trade.get("time", ""))
    snippet = trade_narrative_snippet(trade)
    reason = trade.get("reason", "")

    log_files: list[Path] = []
    bot_log = log_dir / "bot.log"
    if bot_log.exists():
        log_files.append(bot_log)
    log_files.extend(sorted(log_dir.glob("*_PDT.log"), reverse=True))

    for path in log_files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if snippet in text:
            return True, f"Matched narrative in {path.name}"
        if reason and reason[:40] in text:
            return True, f"Matched reason in {path.name}"

    if trade_time:
        for path in log_files[:12]:
            receipt_like = path.name[:10].replace("-", "")
            try:
                file_day = datetime.strptime(receipt_like[:8], "%Y%m%d").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if abs((file_day.date() - trade_time.date()).days) > 2:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if trade.get("from_asset", "") in text and trade.get("to_asset", "") in text:
                if "Traded " in text:
                    return True, f"Weak match (assets + Traded) in {path.name}"

    return False, f"No log line within ~{window_minutes}m window"


def infer_initial_balances(current_balances: dict[str, float], trades: list[dict]) -> dict[str, float]:
    """Reverse all recorded trades from current balances to recover session start."""
    balances = {k: float(v) for k, v in current_balances.items()}
    for trade in reversed(trades):
        _reverse_trade_on_balances(balances, trade)
    return balances


def replay_balances_before(
    trades: list[dict],
    index: int,
    initial_balances: dict[str, float],
) -> dict[str, float]:
    balances = dict(initial_balances)
    for trade in trades[:index]:
        _apply_trade_to_balances(balances, trade)
    return balances


def _apply_trade_to_balances(balances: dict[str, float], trade: dict) -> None:
    legs = trade.get("legs") or [trade]
    for leg in legs:
        from_a = leg.get("from_asset") or trade.get("from_asset")
        to_a = leg.get("to_asset") or trade.get("to_asset")
        from_qty = float(leg.get("from_qty", 0))
        to_qty = float(leg.get("to_qty", 0))
        if from_a:
            balances[from_a] = balances.get(from_a, 0.0) - from_qty
        if to_a:
            balances[to_a] = balances.get(to_a, 0.0) + to_qty


def _reverse_trade_on_balances(balances: dict[str, float], trade: dict) -> None:
    legs = list(reversed(trade.get("legs") or [trade]))
    for leg in legs:
        from_a = leg.get("from_asset") or trade.get("from_asset")
        to_a = leg.get("to_asset") or trade.get("to_asset")
        from_qty = float(leg.get("from_qty", 0))
        to_qty = float(leg.get("to_qty", 0))
        if from_a:
            balances[from_a] = balances.get(from_a, 0.0) + from_qty
        if to_a:
            balances[to_a] = balances.get(to_a, 0.0) - to_qty


def parse_receipt_detail(path: Path) -> dict | None:
    event = parse_receipt(path)
    if not event:
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    time_m = _RECEIPT_TIME.search(text)
    traded_m = _TRADED_LINE.search(text)
    return {
        "file": path.name,
        "time": time_m.group(1).strip() if time_m else "",
        "narrative": traded_m.group(1).strip() if traded_m else event.narrative,
        "reason": event.reason,
        "fee_usd": event.fee_usd,
    }


def estimate_trade_usd(trade: dict, usd_prices: dict[str, float] | None = None) -> float:
    from_a = trade["from_asset"]
    to_a = trade.get("to_asset", "")
    from_qty = float(trade.get("from_qty", 0))
    price = float(trade.get("price", 0))
    symbol = trade.get("symbol", "")

    if from_a == "USD":
        return from_qty
    if to_a == "USD" and price > 0:
        # Selling alt → USD: notional is base qty × execution price.
        return from_qty * price

    if "/" in symbol:
        base, quote = symbol.split("/", 1)
        if from_a == base and quote == "USD" and price > 0:
            return from_qty * price
        if from_a == quote and price > 0:
            if quote == "USD":
                return from_qty
            if quote == "ETH" and usd_prices and "ETH" in usd_prices:
                return from_qty * usd_prices["ETH"]
            if quote == "BTC" and usd_prices and "BTC" in usd_prices:
                return from_qty * usd_prices["BTC"]

    if usd_prices and from_a in usd_prices:
        return from_qty * usd_prices[from_a]
    return from_qty
