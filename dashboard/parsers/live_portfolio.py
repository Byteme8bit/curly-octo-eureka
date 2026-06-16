"""Live Kraken portfolio snapshot for the dashboard."""

from __future__ import annotations

import json
from pathlib import Path

from bot.local_time import format_pacific

from bot.live_portfolio import load_live_usd_prices

from dashboard.config import DashboardSettings

_SKIP_DISPLAY = frozenset({"KFEE", "BABY", "BCH"})


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _load_usd_prices(settings: DashboardSettings) -> dict[str, float]:
    """Best-effort USD prices — session anchor merged with paper snapshot."""
    return load_live_usd_prices(
        live_session_start_file=settings.live_session_start_file,
        paper_portfolio_file=settings.paper_portfolio_file,
    )


def _portfolio_usd(balances: dict[str, float], usd_prices: dict[str, float]) -> float:
    total = 0.0
    for asset, qty in balances.items():
        if qty <= 0 or asset in _SKIP_DISPLAY:
            continue
        if asset == "USD":
            total += qty
        else:
            total += qty * usd_prices.get(asset, 0.0)
    return total


def _holdings_rows(
    balances: dict[str, float],
    usd_prices: dict[str, float],
) -> list[dict]:
    rows: list[dict] = []
    for asset, qty in sorted(balances.items()):
        if qty <= 0 or asset in _SKIP_DISPLAY:
            continue
        price = 1.0 if asset == "USD" else float(usd_prices.get(asset, 0.0))
        rows.append({
            "asset": asset,
            "qty": round(qty, 8),
            "usd_price": round(price, 6),
            "usd_value": round(qty * price, 2),
        })
    rows.sort(key=lambda r: -r["usd_value"])
    return rows


def _live_trade_rows(trades: list) -> list[dict]:
    rows: list[dict] = []
    for trade in reversed(trades):
        if not isinstance(trade, dict) or not trade.get("live"):
            continue
        side = str(trade.get("side", ""))
        symbol = str(trade.get("symbol", ""))
        from_asset = trade.get("from_asset", "")
        to_asset = trade.get("to_asset", "")
        gain = trade.get("gain_loss")
        rows.append({
            "file": trade.get("order_id", ""),
            "time": str(trade.get("time", "")),
            "summary": f"{side} {symbol} ({from_asset}→{to_asset})".strip(),
            "gain_loss": f"${float(gain):+.2f}" if gain is not None else "",
            "gain_loss_usd": float(gain) if gain is not None else None,
            "fee_usd": float(trade.get("fee_usd", 0.0) or 0.0),
        })
    return rows


def _live_guardrails(
    settings: DashboardSettings,
    *,
    balances: dict[str, float],
    drawdown_pct: float,
    trade_count: int,
    risk: dict,
) -> dict:
    eth_qty = float(balances.get("ETH", 0.0))
    floor = settings.live_min_eth_reserve
    dd_limit = settings.live_drawdown_halt_pct
    max_trades = settings.live_max_trades
    reasons: list[str] = []

    if eth_qty < floor:
        reasons.append(f"ETH {eth_qty:.4f} below floor {floor:.1f}")
    if drawdown_pct >= dd_limit - 1e-9:
        reasons.append(f"Drawdown {drawdown_pct:.1%} at/above {dd_limit:.0%} halt")
    if max_trades > 0 and trade_count >= max_trades:
        reasons.append(f"Live trade limit reached ({trade_count}/{max_trades})")
    if risk.get("circuit_breaker_at"):
        reasons.append("Circuit breaker active")

    return {
        "halted": bool(reasons),
        "halt_reasons": reasons,
        "eth_balance": round(eth_qty, 8),
        "eth_floor": floor,
        "drawdown_pct": round(drawdown_pct, 6),
        "drawdown_halt_pct": dd_limit,
        "max_trades": max_trades,
        "trades_completed": trade_count,
        "trades_remaining": max(0, max_trades - trade_count) if max_trades > 0 else None,
        "mirror_mode": settings.live_mirror_paper and settings.live_enabled,
    }


def load_live_portfolio(settings: DashboardSettings) -> dict | None:
    """Build portfolio metrics from ``.live_state.json`` risk + balances."""
    state = _read_json(settings.live_state_file)
    if not state:
        return None

    balances_raw = state.get("balances") or {}
    if not isinstance(balances_raw, dict):
        return None
    balances = {str(k): float(v) for k, v in balances_raw.items()}

    risk = state.get("risk") or {}
    baseline = float(risk.get("baseline_portfolio", 0.0))
    peak = float(risk.get("peak_portfolio", 0.0))
    usd_prices = _load_usd_prices(settings)
    portfolio_usd = _portfolio_usd(balances, usd_prices)

    baseline_pnl = portfolio_usd - baseline if baseline > 0 else 0.0
    drawdown_pct = max(0.0, (peak - portfolio_usd) / peak) if peak > 0 else 0.0

    holdings = _holdings_rows(balances, usd_prices)
    cash_usd = sum(r["usd_value"] for r in holdings if r["asset"] == "USD")
    total = portfolio_usd or 0.0
    cash_pct = round(cash_usd / total, 4) if total > 0 else None

    session = _read_json(settings.live_session_start_file)
    anchored_at = ""
    if session:
        anchored_at = str(session.get("anchored_at_pacific", ""))

    return {
        "mode": "live",
        "updated_at": format_pacific(),
        "anchored_at": anchored_at,
        "portfolio_usd": round(portfolio_usd, 2),
        "baseline_portfolio_usd": round(baseline, 2),
        "peak_portfolio_usd": round(peak, 2),
        "baseline_pnl": round(baseline_pnl, 2),
        "drawdown_pct": round(drawdown_pct, 6),
        "cash_usd": round(cash_usd, 2),
        "cash_pct": cash_pct,
        "trade_count": int(risk.get("live_trades_completed", 0)),
        "holdings": holdings,
        "live_trades": _live_trade_rows(state.get("trades") or []),
        "live_guardrails": _live_guardrails(
            settings,
            balances=balances,
            drawdown_pct=drawdown_pct,
            trade_count=int(risk.get("live_trades_completed", 0)),
            risk=risk if isinstance(risk, dict) else {},
        ),
    }
