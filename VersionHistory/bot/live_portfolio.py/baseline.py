"""Live Kraken spot portfolio metrics — shared by WatchDog, TradeBot, auditor."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_SKIP_DISPLAY = frozenset({"KFEE", "BABY", "BCH"})


@dataclass(frozen=True)
class LivePortfolioSnapshot:
    portfolio_usd: float
    baseline_portfolio_usd: float
    session_pnl: float
    drawdown_pct: float
    peak_portfolio_usd: float


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _load_usd_prices(
    *,
    live_session_start_file: Path,
    paper_portfolio_file: Path | None = None,
) -> dict[str, float]:
    if paper_portfolio_file is not None:
        paper = _read_json(paper_portfolio_file)
        if paper:
            prices: dict[str, float] = {"USD": 1.0}
            for asset, row in (paper.get("holdings") or {}).items():
                if isinstance(row, dict):
                    px = float(row.get("usd_price", 0.0))
                    if px > 0:
                        prices[str(asset)] = px
            if len(prices) > 1:
                return prices

    session = _read_json(live_session_start_file)
    if session:
        raw = session.get("usd_prices") or {}
        return {str(k): float(v) for k, v in raw.items() if isinstance(v, (int, float))}
    return {"USD": 1.0}


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


def load_live_portfolio_snapshot(
    *,
    live_state_file: Path,
    live_session_start_file: Path,
    paper_portfolio_file: Path | None = None,
) -> LivePortfolioSnapshot | None:
    """Build live spot metrics from ``.live_state.json`` (+ session anchor fallback)."""
    state = _read_json(live_state_file)
    if not state:
        return None

    balances_raw = state.get("balances") or {}
    if not isinstance(balances_raw, dict):
        return None
    balances = {str(k): float(v) for k, v in balances_raw.items()}

    risk = state.get("risk") or {}
    baseline = float(risk.get("baseline_portfolio", 0.0)) if isinstance(risk, dict) else 0.0
    peak = float(risk.get("peak_portfolio", 0.0)) if isinstance(risk, dict) else 0.0

    session = _read_json(live_session_start_file)
    if baseline <= 0 and session:
        baseline = float(session.get("baseline_portfolio_usd", 0.0))
    if peak <= 0 and session:
        peak = float(session.get("peak_portfolio_usd", baseline))

    usd_prices = _load_usd_prices(
        live_session_start_file=live_session_start_file,
        paper_portfolio_file=paper_portfolio_file,
    )
    portfolio_usd = _portfolio_usd(balances, usd_prices)
    session_pnl = portfolio_usd - baseline if baseline > 0 else 0.0
    drawdown_pct = max(0.0, (peak - portfolio_usd) / peak) if peak > 0 else 0.0

    return LivePortfolioSnapshot(
        portfolio_usd=portfolio_usd,
        baseline_portfolio_usd=baseline,
        session_pnl=session_pnl,
        drawdown_pct=drawdown_pct,
        peak_portfolio_usd=peak,
    )
