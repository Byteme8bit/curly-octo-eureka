"""TradeBot tab — portfolio, ticks, trades, blocked opportunities."""

from __future__ import annotations

import json
import re
from pathlib import Path

from bot.paper_portfolio import PaperPortfolioLog

from dashboard.config import DashboardSettings
from dashboard.io_util import newest_files, read_text, tail_lines
from dashboard.parsers.live_portfolio import load_live_portfolio

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
_FEE_USD = re.compile(r"^Fee:\s+\$?([\d,.]+)", re.MULTILINE)
_GAIN_NUM = re.compile(r"([+-]?)\$?([\d,.]+)")


def _parse_gain_loss_usd(raw: str) -> float | None:
    if not raw:
        return None
    m = _GAIN_NUM.search(raw.replace(",", ""))
    if not m:
        return None
    sign = -1.0 if m.group(1) == "-" or raw.strip().startswith("-") else 1.0
    try:
        return sign * float(m.group(2))
    except ValueError:
        return None


def _parse_receipt(path: Path) -> dict | None:
    raw = read_text(path)
    if not raw or "TRADE RECEIPT" not in raw:
        return None
    time_m = _RECEIPT_TIME.search(raw)
    traded_m = _TRADED_LINE.search(raw)
    gl_m = _GAIN_LOSS.search(raw)
    fee_m = _FEE_USD.search(raw)
    gain_raw = gl_m.group(1).strip() if gl_m else ""
    fee_usd = None
    if fee_m:
        try:
            fee_usd = float(fee_m.group(1).replace(",", ""))
        except ValueError:
            fee_usd = None
    return {
        "file": path.name,
        "time": time_m.group(1).strip() if time_m else "",
        "summary": traded_m.group(1).strip() if traded_m else "",
        "gain_loss": gain_raw,
        "gain_loss_usd": _parse_gain_loss_usd(gain_raw),
        "fee_usd": fee_usd,
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


def _equity_holdings(
    portfolio: dict | None,
    equity_assets: frozenset[str],
) -> list[dict]:
    if not portfolio or not equity_assets:
        return []
    rows: list[dict] = []
    for row in portfolio.get("holdings") or []:
        asset = row.get("asset", "")
        if asset in equity_assets and float(row.get("qty") or 0) > 0:
            rows.append({**row, "asset_class": "equity"})
    return rows


def _build_paper_portfolio(settings: DashboardSettings) -> dict | None:
    portfolio_log = PaperPortfolioLog(settings.paper_portfolio_file)
    snap = portfolio_log.load()
    if snap is None and settings.paper_state_file.exists():
        snap = portfolio_log.bootstrap_from_state(settings.paper_state_file)
    if snap is None:
        return None

    # Qty source of truth: .paper_state.json (updates on every fill).
    # Prices/values: prefer latest paper_portfolio snapshot, recompute value.
    state_balances: dict[str, float] = {}
    if settings.paper_state_file.exists():
        try:
            raw = json.loads(settings.paper_state_file.read_text(encoding="utf-8"))
            bal = raw.get("balances") or {}
            if isinstance(bal, dict):
                state_balances = {str(k): float(v) for k, v in bal.items()}
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            state_balances = {}

    price_by_asset = {
        asset: float(row.get("usd_price") or 0.0)
        for asset, row in (snap.holdings or {}).items()
    }
    if "USD" not in price_by_asset:
        price_by_asset["USD"] = 1.0

    assets = set(state_balances) | set(snap.holdings)
    holdings_rows: list[dict] = []
    for asset in assets:
        qty = float(state_balances.get(asset, snap.holdings.get(asset, {}).get("qty", 0.0) or 0.0))
        if qty <= 0:
            continue
        price = 1.0 if asset == "USD" else float(price_by_asset.get(asset, 0.0) or 0.0)
        # Fall back to snapshot usd_value/qty if price missing
        if price <= 0 and asset in snap.holdings:
            row = snap.holdings[asset]
            sq = float(row.get("qty") or 0.0)
            if sq > 0:
                price = float(row.get("usd_value") or 0.0) / sq
        usd_value = round(qty * price, 2) if price > 0 else float(
            (snap.holdings.get(asset) or {}).get("usd_value") or 0.0
        )
        holdings_rows.append({
            "asset": asset,
            "qty": qty,
            "usd_price": round(price, 6),
            "usd_value": usd_value,
        })
    holdings_rows.sort(key=lambda r: -float(r["usd_value"]))

    cash_usd = sum(r["usd_value"] for r in holdings_rows if r["asset"] == "USD")
    total = snap.portfolio_usd or sum(r["usd_value"] for r in holdings_rows) or 0.0
    cash_pct = round(cash_usd / total, 4) if total > 0 else None
    eth_qty = next((r["qty"] for r in holdings_rows if r["asset"] == "ETH"), None)
    eth_baseline = None
    baseline_path = settings.root / "paper_baseline.json"
    if baseline_path.exists():
        try:
            base = json.loads(baseline_path.read_text(encoding="utf-8"))
            eth_baseline = float((base.get("balances") or {}).get("ETH") or 0.0) or None
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            eth_baseline = None
    eth_delta = None
    if eth_qty is not None and eth_baseline is not None:
        eth_delta = eth_qty - eth_baseline

    last_fill_delta = None
    last_fill_asset = None
    if settings.paper_state_file.exists():
        try:
            raw = json.loads(settings.paper_state_file.read_text(encoding="utf-8"))
            trades = raw.get("trades") or []
            if trades:
                t = trades[-1]
                hops = int(t.get("hops") or 1)
                if hops > 1 and t.get("from_asset") and t.get("from_asset") == t.get("to_asset"):
                    last_fill_asset = str(t.get("from_asset"))
                    last_fill_delta = float(t.get("to_qty") or 0.0) - float(t.get("from_qty") or 0.0)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass

    return {
        "mode": "paper",
        "updated_at": snap.updated_at,
        "portfolio_usd": snap.portfolio_usd,
        "baseline_pnl": snap.baseline_pnl,
        "drawdown_pct": snap.drawdown_pct,
        "cash_usd": round(cash_usd, 2),
        "cash_pct": cash_pct,
        "eth_qty": eth_qty,
        "eth_baseline": eth_baseline,
        "eth_delta": eth_delta,
        "last_fill_asset": last_fill_asset,
        "last_fill_delta": last_fill_delta,
        "trade_count": 0,
        "holdings": holdings_rows,
    }


def _paper_state_trade_count(settings: DashboardSettings) -> int:
    state_path = settings.paper_state_file
    if not state_path.exists():
        return 0
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    trades = data.get("trades") or []
    return len(trades) if isinstance(trades, list) else 0


def _paper_receipts(settings: DashboardSettings, *, limit: int = 50) -> list[dict]:
    receipts: list[dict] = []
    seen: set[str] = set()
    for path in newest_files(settings.receipts_dir, "*.txt", limit=limit):
        row = _parse_receipt(path)
        if row:
            receipts.append(row)
            ts = row.get("time", "")
            if ts:
                seen.add(ts)

    state_path = settings.paper_state_file
    if state_path.exists():
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        for trade in reversed(data.get("trades") or []):
            if not isinstance(trade, dict):
                continue
            ts = str(trade.get("time", ""))
            if not ts or ts in seen:
                continue
            from_a = trade.get("from_asset", "?")
            to_a = trade.get("to_asset", "?")
            path = trade.get("path") or f"{from_a}->{to_a}"
            strat = trade.get("strategy_name") or ""
            prefix = f"[{strat}] " if strat else ""
            receipts.append({
                "time": ts,
                "summary": f"{prefix}{path} {trade.get('reason', '')}".strip(),
                "gain_loss_usd": trade.get("gain_loss"),
                "fee_usd": trade.get("fee_usd") or trade.get("fee_quote"),
            })
            seen.add(ts)
            if len(receipts) >= limit:
                break

    return receipts[:limit]


def _build_paper_tradebot_view(settings: DashboardSettings) -> dict:
    portfolio = _build_paper_portfolio(settings)
    receipts = _paper_receipts(settings, limit=50)
    trade_count = _paper_state_trade_count(settings)
    if portfolio is not None:
        portfolio = {**portfolio, "trade_count": trade_count}

    log_text = _load_window_logs(settings.log_dir)
    ticks = _extract_ticks_from_log(log_text)
    latest = ticks[-1] if ticks else None
    discord_lines = tail_lines(settings.discord_chat_log, max_lines=400)
    strategy_focus = _strategy_focus(latest, discord_lines)

    blocked_all: list[str] = []
    if latest:
        blocked_all.extend(latest.get("blocked") or [])
        blocked_all.extend(latest.get("rotation_blocked") or [])

    return {
        "mode": "paper",
        "portfolio": portfolio,
        "equity_holdings": _equity_holdings(portfolio, settings.equity_assets),
        "live_portfolio": None,
        "live_guardrails": None,
        "latest_tick": latest,
        "pnl_trend": _pnl_trend(ticks),
        "recent_ticks": ticks[-5:],
        "recent_trades": receipts,
        "blocked_opportunities": blocked_all[:20],
        "strategy_focus": strategy_focus,
        "runtime_log_tail": tail_lines(settings.runtime_log, max_lines=40),
        "sources": {
            "portfolio": str(settings.paper_portfolio_file),
            "paper_state": str(settings.paper_state_file),
            "live_portfolio": None,
            "session_anchor": None,
            "logs": str(settings.log_dir),
            "receipts": str(settings.receipts_dir),
        },
    }


def _build_live_tradebot_view(settings: DashboardSettings) -> dict:
    live = load_live_portfolio(settings)
    portfolio = None
    live_trades: list[dict] = []
    if live:
        portfolio = {
            k: live[k]
            for k in (
                "mode",
                "updated_at",
                "anchored_at",
                "portfolio_usd",
                "baseline_portfolio_usd",
                "peak_portfolio_usd",
                "baseline_pnl",
                "drawdown_pct",
                "cash_usd",
                "cash_pct",
                "trade_count",
                "holdings",
            )
        }
        live_trades = live.get("live_trades") or []

    log_text = _load_window_logs(settings.log_dir)
    ticks = _extract_ticks_from_log(log_text)
    latest = ticks[-1] if ticks else None
    discord_lines = tail_lines(settings.discord_chat_log, max_lines=400)
    strategy_focus = _strategy_focus(latest, discord_lines)

    blocked_all: list[str] = []
    if latest:
        blocked_all.extend(latest.get("blocked") or [])
        blocked_all.extend(latest.get("rotation_blocked") or [])

    return {
        "mode": "live",
        "portfolio": portfolio,
        "equity_holdings": _equity_holdings(portfolio, settings.equity_assets),
        "live_portfolio": live,
        "live_guardrails": live.get("live_guardrails") if live else None,
        "latest_tick": latest,
        "pnl_trend": [],
        "recent_ticks": ticks[-5:],
        "recent_trades": live_trades[:15],
        "blocked_opportunities": blocked_all[:20],
        "strategy_focus": strategy_focus,
        "runtime_log_tail": tail_lines(settings.runtime_log, max_lines=40),
        "sources": {
            "portfolio": str(settings.live_state_file),
            "paper_state": None,
            "live_portfolio": str(settings.live_state_file),
            "session_anchor": str(settings.live_session_start_file),
            "logs": str(settings.log_dir),
            "receipts": str(settings.receipts_dir),
        },
    }


def build_tradebot_view(settings: DashboardSettings, *, mode: str = "paper") -> dict:
    """Build TradeBot panel for ``paper`` or ``live`` dashboard mode."""
    normalized = (mode or "paper").lower()
    if normalized == "live":
        return _build_live_tradebot_view(settings)
    return _build_paper_tradebot_view(settings)
