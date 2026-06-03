"""TradeBot tab — portfolio, ticks, trades, blocked opportunities."""

from __future__ import annotations

import re
from pathlib import Path

from bot.paper_portfolio import PaperPortfolioLog

from dashboard.config import DashboardSettings
from dashboard.io_util import newest_files, read_text, tail_lines

_TICK_HEADER = re.compile(
    r"^MARKET CHECK - (.+)$",
    re.MULTILINE,
)
_PORTFOLIO_LINE = re.compile(
    r"^Portfolio:\s+\$([\d,]+\.\d+)\s+\(PnL\s+([+-]?[\d.]+)\s+\|\s+drawdown\s+([\d.]+%)\)",
    re.MULTILINE,
)
_DECISION = re.compile(r"^Decision:\s+(\w+)", re.MULTILINE)
_RECEIPT_TIME = re.compile(r"^Time:\s+(.+)$", re.MULTILINE)
_TRADED_LINE = re.compile(r"^Traded (.+)$", re.MULTILINE)
_GAIN_LOSS = re.compile(r"^Gain/Loss:\s+(.+)$", re.MULTILINE)


def _parse_receipt(path: Path) -> dict | None:
    raw = read_text(path)
    if not raw or "TRADE RECEIPT" not in raw:
        return None
    time_m = _RECEIPT_TIME.search(raw)
    traded_m = _TRADED_LINE.search(raw)
    gl_m = _GAIN_LOSS.search(raw)
    return {
        "file": path.name,
        "time": time_m.group(1).strip() if time_m else "",
        "summary": traded_m.group(1).strip() if traded_m else "",
        "gain_loss": gl_m.group(1).strip() if gl_m else "",
    }


def _extract_ticks_from_log(text: str, *, max_ticks: int = 30) -> list[dict]:
    ticks: list[dict] = []
    if not text:
        return ticks
    for header in _TICK_HEADER.finditer(text):
        start = header.start()
        next_tick = text.find("\nMARKET CHECK - ", start + 12)
        if next_tick < 0:
            block = text[start : start + 12000]
        else:
            block = text[start:next_tick]
        ts = header.group(1).strip()
        port_m = _PORTFOLIO_LINE.search(block)
        decision_m = _DECISION.search(block)
        blocked: list[str] = []
        rotation: list[str] = []
        considering: list[str] = []
        in_risk = False
        in_rotation = False
        in_considering = False
        for line in block.splitlines():
            stripped = line.strip()
            if stripped == "Risk gate:":
                in_risk = True
                in_rotation = False
                in_considering = False
                continue
            if stripped == "Rotation options:":
                in_rotation = True
                in_risk = False
                in_considering = False
                continue
            if stripped == "Considering:":
                in_considering = True
                in_risk = False
                in_rotation = False
                continue
            if stripped.startswith("Decision:") or stripped.startswith("Momentum:"):
                in_risk = in_rotation = in_considering = False
            if in_risk and stripped.startswith("["):
                blocked.append(stripped)
            elif in_rotation and stripped and not stripped.startswith("Rotation"):
                if "below fee hurdle" in stripped:
                    rotation.append(stripped)
            elif in_considering and stripped and not stripped.startswith("Considering"):
                considering.append(stripped)
        tick = {
            "time": ts,
            "decision": decision_m.group(1) if decision_m else "",
            "portfolio_usd": None,
            "baseline_pnl": None,
            "drawdown_pct": None,
            "blocked": blocked[:12],
            "rotation_blocked": rotation[:10],
            "considering": considering[:8],
        }
        if port_m:
            tick["portfolio_usd"] = float(port_m.group(1).replace(",", ""))
            tick["baseline_pnl"] = float(port_m.group(2))
            tick["drawdown_pct"] = port_m.group(3)
        ticks.append(tick)
    return ticks[-max_ticks:]


def _pnl_trend(ticks: list[dict]) -> list[dict]:
    out: list[dict] = []
    for t in ticks:
        if t.get("portfolio_usd") is not None:
            out.append({
                "time": t["time"],
                "portfolio_usd": t["portfolio_usd"],
                "baseline_pnl": t["baseline_pnl"],
            })
    return out


def _strategy_focus(latest_tick: dict | None, discord_lines: list[str]) -> str:
    if latest_tick and latest_tick.get("considering"):
        return "; ".join(latest_tick["considering"][:3])
    for line in reversed(discord_lines):
        if "Current focus" in line or "**Current focus**" in line:
            return line.split("Current focus", 1)[-1].strip(" |")
    return ""


def _load_window_logs(log_dir: Path, *, max_files: int = 2) -> str:
    chunks: list[str] = []
    for path in newest_files(log_dir, "*_PDT.log", limit=max_files):
        text = read_text(path)
        if text:
            chunks.append(text)
    return "\n".join(chunks)


def build_tradebot_view(settings: DashboardSettings) -> dict:
    portfolio_log = PaperPortfolioLog(settings.paper_portfolio_file)
    snap = portfolio_log.load()
    if snap is None and settings.paper_state_file.exists():
        snap = portfolio_log.bootstrap_from_state(settings.paper_state_file)

    receipts = []
    for path in newest_files(settings.receipts_dir, "*.txt", limit=15):
        row = _parse_receipt(path)
        if row:
            receipts.append(row)

    log_text = _load_window_logs(settings.log_dir)
    ticks = _extract_ticks_from_log(log_text)
    latest = ticks[-1] if ticks else None

    discord_lines = tail_lines(settings.discord_chat_log, max_lines=400)
    strategy_focus = _strategy_focus(latest, discord_lines)

    portfolio = None
    if snap:
        portfolio = {
            "updated_at": snap.updated_at,
            "portfolio_usd": snap.portfolio_usd,
            "baseline_pnl": snap.baseline_pnl,
            "drawdown_pct": snap.drawdown_pct,
            "holdings": [
                {
                    "asset": asset,
                    "qty": row["qty"],
                    "usd_price": row["usd_price"],
                    "usd_value": row["usd_value"],
                }
                for asset, row in sorted(
                    snap.holdings.items(),
                    key=lambda x: -x[1]["usd_value"],
                )
            ],
        }

    blocked_all: list[str] = []
    if latest:
        blocked_all.extend(latest.get("blocked") or [])
        blocked_all.extend(latest.get("rotation_blocked") or [])

    runtime_tail = tail_lines(settings.runtime_log, max_lines=40)

    return {
        "portfolio": portfolio,
        "latest_tick": latest,
        "pnl_trend": _pnl_trend(ticks),
        "recent_ticks": ticks[-5:],
        "recent_trades": receipts,
        "blocked_opportunities": blocked_all[:20],
        "strategy_focus": strategy_focus,
        "runtime_log_tail": runtime_tail,
        "sources": {
            "portfolio": str(settings.paper_portfolio_file),
            "logs": str(settings.log_dir),
            "receipts": str(settings.receipts_dir),
        },
    }
