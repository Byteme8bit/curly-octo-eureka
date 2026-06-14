"""Time-series and forecast data for dashboard charts."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from dashboard.config import DashboardSettings
from dashboard.io_util import newest_files, read_text
from dashboard.parsers.tradebot import _extract_ticks_from_log, _load_window_logs, _parse_receipt

_FORECAST_SECTION = re.compile(
    r"## Forecast\s*\n(.*?)(?=\n## |\Z)",
    re.DOTALL,
)
_FORECAST_ROW = re.compile(
    r"^\|\s*(\S+)\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*$",
    re.MULTILINE,
)
_MONEY = re.compile(r"[\$,\s]+")


def _parse_money(raw: str) -> float | None:
    s = raw.strip()
    if not s or s in ("—", "-", "N/A"):
        return None
    neg = s.startswith("-") or s.startswith("($")
    cleaned = _MONEY.sub("", s.replace("(", "").replace(")", ""))
    try:
        val = float(cleaned)
    except ValueError:
        return None
    return -val if neg and val > 0 else val


def _parse_confidence(raw: str) -> float | None:
    s = raw.strip()
    try:
        return float(s)
    except ValueError:
        return None


def parse_forecast_table(raw: str) -> list[dict]:
    """Parse ## Forecast markdown table from an audit report."""
    if not raw:
        return []
    section_m = _FORECAST_SECTION.search(raw)
    if not section_m:
        return []
    body = section_m.group(1)
    bands: list[dict] = []
    for row in _FORECAST_ROW.finditer(body):
        horizon, method, expected, lower, upper, confidence = row.groups()
        if horizon.lower() == "horizon" or method.strip() == "---":
            continue
        bands.append({
            "horizon": horizon.strip(),
            "method": method.strip(),
            "expected_pnl": _parse_money(expected),
            "lower_band": _parse_money(lower),
            "upper_band": _parse_money(upper),
            "confidence": _parse_confidence(confidence),
        })
    return bands


def _latest_audit_report_path(reports_dir: Path) -> Path | None:
    found: list[tuple[float, Path]] = []
    if not reports_dir.is_dir():
        return None
    for day_dir in reports_dir.iterdir():
        if not day_dir.is_dir():
            continue
        for path in day_dir.glob("audit-*.md"):
            try:
                found.append((path.stat().st_mtime, path))
            except OSError:
                continue
    if not found:
        return None
    found.sort(key=lambda x: x[0], reverse=True)
    return found[0][1]


def build_forecasts(settings: DashboardSettings) -> dict:
    """Best-effort forecasts from the latest audit report."""
    path = _latest_audit_report_path(settings.reports_dir)
    if path is None:
        return {"source": None, "report_title": "", "bands": [], "disclaimer": ""}
    raw = read_text(path) or ""
    title_m = re.search(r"^# Auditor report — (.+)$", raw, re.MULTILINE)
    bands = parse_forecast_table(raw)
    return {
        "source": str(path),
        "report_title": title_m.group(1).strip() if title_m else path.stem,
        "bands": bands,
        "disclaimer": "Confidence is heuristic only; bands are not investment advice.",
    }


def build_portfolio_history(settings: DashboardSettings, *, max_ticks: int = 120) -> dict:
    """Portfolio value time series from window logs + current snapshot."""
    log_text = _load_window_logs(settings.log_dir, max_files=8)
    ticks = _extract_ticks_from_log(log_text, max_ticks=max_ticks)
    points: list[dict] = []
    for t in ticks:
        if t.get("portfolio_usd") is None:
            continue
        dd = t.get("drawdown_pct")
        dd_val = None
        if isinstance(dd, str) and dd.endswith("%"):
            try:
                dd_val = float(dd.rstrip("%")) / 100.0
            except ValueError:
                dd_val = None
        elif isinstance(dd, (int, float)):
            dd_val = float(dd)
        points.append({
            "time": t["time"],
            "portfolio_usd": t["portfolio_usd"],
            "baseline_pnl": t.get("baseline_pnl"),
            "drawdown_pct": dd_val,
        })

    pnl_deltas: list[dict] = []
    for i in range(1, len(points)):
        prev = points[i - 1]
        cur = points[i]
        if prev.get("baseline_pnl") is not None and cur.get("baseline_pnl") is not None:
            pnl_deltas.append({
                "time": cur["time"],
                "delta_pnl": round(cur["baseline_pnl"] - prev["baseline_pnl"], 4),
            })

    return {
        "points": points,
        "pnl_deltas": pnl_deltas,
        "source": str(settings.log_dir),
    }


def _parse_receipt_time(time_str: str) -> str:
    """Return YYYY-MM-DD bucket key from receipt time line."""
    s = time_str.strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    for fmt in ("%Y-%m-%d %H:%M:%S %Z", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[:19], fmt[:19]).strftime("%Y-%m-%d")
        except ValueError:
            continue
    parts = s.split()
    if len(parts) >= 1 and len(parts[0]) == 10:
        return parts[0]
    return s[:10] if len(s) >= 10 else "unknown"


def build_trades_series(settings: DashboardSettings, *, receipt_limit: int = 200) -> dict:
    """Trade counts and net PnL grouped by day from receipts."""
    buckets: dict[str, dict] = defaultdict(lambda: {"trade_count": 0, "net_pnl": 0.0, "fees": 0.0})
    trades: list[dict] = []

    for path in newest_files(settings.receipts_dir, "*.txt", limit=receipt_limit):
        row = _parse_receipt(path)
        if not row:
            continue
        day = _parse_receipt_time(row.get("time", ""))
        pnl = row.get("gain_loss_usd")
        fee = row.get("fee_usd") or 0.0
        buckets[day]["trade_count"] += 1
        if pnl is not None:
            buckets[day]["net_pnl"] += pnl
        buckets[day]["fees"] += fee
        trades.append({
            "time": row.get("time", ""),
            "summary": row.get("summary", ""),
            "gain_loss_usd": pnl,
            "fee_usd": fee,
        })

    series = []
    for day in sorted(buckets.keys()):
        b = buckets[day]
        series.append({
            "bucket": day,
            "trade_count": b["trade_count"],
            "net_pnl": round(b["net_pnl"], 2),
            "fees": round(b["fees"], 2),
        })

    return {
        "buckets": series,
        "recent": trades[:30],
        "source": str(settings.receipts_dir),
    }
