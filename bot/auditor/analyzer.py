"""Pure analysis functions over the broker trade history.

No I/O, no network, no time. Callers pre-load trades + holdings + prices.
Everything here is deterministic so tests can pin behavior with synthetic data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import fmean
from typing import Iterable


@dataclass(frozen=True)
class StrategyPerformance:
    strategy: str
    trade_count: int
    wins: int
    losses: int
    win_rate: float
    avg_gain: float
    avg_loss: float
    total_pnl: float
    total_fees: float
    fee_drag_ratio: float        # fees / max(|pnl|, eps); >1 means fees > absolute pnl
    best_trade: float
    worst_trade: float
    pairs_used: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PortfolioInsights:
    period_start: str
    period_end: str
    total_trades: int
    total_pnl: float
    total_fees: float
    net_pnl: float                              # pnl - fees
    win_rate: float
    by_strategy: list[StrategyPerformance]
    by_asset_concentration: dict[str, float]    # asset -> share of portfolio (0..1)
    over_concentrated: list[str]                # non-ETH/BTC assets above MAX_ALT_ALLOCATION_PCT
    eth_reserve_status: dict                    # current_eth, min_required, healthy
    drawdown_max: float                          # max running-sum equity drawdown seen
    recent_circuit_breaker_events: int          # heuristic: trades flagged defensive/circuit
    top_pair_strategy: list[tuple[str, str, float]] = field(default_factory=list)
    bottom_pair_strategy: list[tuple[str, str, float]] = field(default_factory=list)


_DEFENSIVE_HINTS = ("circuit", "re-evaluation", "reevaluation", "defensive", "drawdown")


def _trade_strategy_name(trade: dict) -> str:
    name = (trade.get("strategy_name") or "").strip()
    return name or "unknown"


def _trade_is_defensive(trade: dict) -> bool:
    reason = (trade.get("reason") or "").lower()
    return any(hint in reason for hint in _DEFENSIVE_HINTS)


def _drawdown_from_equity(gains: Iterable[float]) -> float:
    """Worst running drawdown of cumulative gain_loss.

    `gains` is an ordered iterable of per-trade gain/loss values. We treat the
    cumulative sum as an equity curve, then return the largest peak-to-trough
    distance in absolute dollars. Returns 0.0 when there's no drawdown.
    """
    peak = 0.0
    running = 0.0
    worst = 0.0
    for g in gains:
        running += g
        if running > peak:
            peak = running
        dd = peak - running
        if dd > worst:
            worst = dd
    return worst


def _strategy_perf(strategy: str, trades: list[dict]) -> StrategyPerformance:
    gains = [float(t.get("gain_loss", 0.0)) for t in trades]
    fees = [float(t.get("fee_usd", 0.0)) for t in trades]
    wins_list = [g for g in gains if g > 0]
    losses_list = [g for g in gains if g < 0]
    total_pnl = sum(gains)
    total_fees = sum(fees)
    pairs = sorted({str(t.get("symbol") or "") for t in trades if t.get("symbol")})
    abs_pnl = abs(total_pnl)
    fee_drag = (total_fees / abs_pnl) if abs_pnl > 1e-9 else (float("inf") if total_fees > 0 else 0.0)
    return StrategyPerformance(
        strategy=strategy,
        trade_count=len(trades),
        wins=len(wins_list),
        losses=len(losses_list),
        win_rate=(len(wins_list) / len(gains)) if gains else 0.0,
        avg_gain=fmean(wins_list) if wins_list else 0.0,
        avg_loss=fmean(losses_list) if losses_list else 0.0,
        total_pnl=total_pnl,
        total_fees=total_fees,
        fee_drag_ratio=fee_drag,
        best_trade=max(gains) if gains else 0.0,
        worst_trade=min(gains) if gains else 0.0,
        pairs_used=pairs,
    )


def _concentration(
    holdings: dict[str, float],
    usd_prices: dict[str, float] | None,
) -> tuple[dict[str, float], float]:
    """Return (asset -> share, total_usd).

    If `usd_prices` is None we treat ``holdings`` values as already-USD. With
    USD prices we compute qty * price (USD always 1.0).
    """
    values: dict[str, float] = {}
    for asset, qty in holdings.items():
        if qty <= 0:
            continue
        if usd_prices is None:
            values[asset] = float(qty)
        elif asset == "USD":
            values[asset] = float(qty)
        else:
            price = float(usd_prices.get(asset, 0.0))
            if price > 0:
                values[asset] = float(qty) * price
    total = sum(values.values())
    if total <= 0:
        return {}, 0.0
    return {a: v / total for a, v in values.items()}, total


def _pair_strategy_combos(trades: list[dict]) -> list[tuple[str, str, float]]:
    """Aggregate (symbol, strategy) -> total gain_loss across trades."""
    bucket: dict[tuple[str, str], float] = {}
    for t in trades:
        symbol = str(t.get("symbol") or "")
        strat = _trade_strategy_name(t)
        if not symbol:
            continue
        bucket[(symbol, strat)] = bucket.get((symbol, strat), 0.0) + float(t.get("gain_loss", 0.0))
    return sorted(((s, st, v) for (s, st), v in bucket.items()), key=lambda x: x[2], reverse=True)


def analyze_trades(
    trades: list[dict],
    holdings: dict[str, float],
    settings,
    *,
    usd_prices: dict[str, float] | None = None,
) -> PortfolioInsights:
    """Pure-function analyzer over broker trade history.

    Args:
        trades: list of broker trade dicts (`bot.paper_broker`).
        holdings: asset -> quantity. If `usd_prices` is None the values are
            assumed to already be USD; otherwise USD = qty * price.
        settings: full `config.Settings` (for `min_eth_reserve`,
            `max_alt_allocation_pct`).
        usd_prices: optional asset -> USD price for concentration math.

    Returns: a fully populated `PortfolioInsights`.
    """
    trades = list(trades or [])
    period_start = str(trades[0].get("time", "")) if trades else ""
    period_end = str(trades[-1].get("time", "")) if trades else ""

    gains = [float(t.get("gain_loss", 0.0)) for t in trades]
    fees = [float(t.get("fee_usd", 0.0)) for t in trades]
    total_pnl = sum(gains)
    total_fees = sum(fees)
    wins = sum(1 for g in gains if g > 0)
    win_rate = (wins / len(gains)) if gains else 0.0

    by_strategy_groups: dict[str, list[dict]] = {}
    for t in trades:
        by_strategy_groups.setdefault(_trade_strategy_name(t), []).append(t)
    by_strategy = sorted(
        (_strategy_perf(name, group) for name, group in by_strategy_groups.items()),
        key=lambda p: p.total_pnl,
        reverse=True,
    )

    shares, _ = _concentration(holdings, usd_prices)
    cap = float(getattr(settings, "max_alt_allocation_pct", 0.40))
    over = sorted(
        asset for asset, share in shares.items()
        if asset not in ("USD", "ETH", "BTC") and share > cap
    )

    eth_qty = float(holdings.get("ETH", 0.0))
    min_eth = float(getattr(settings, "min_eth_reserve", 0.0))
    eth_status = {
        "current_eth": eth_qty,
        "min_required": min_eth,
        "healthy": eth_qty >= min_eth,
    }

    drawdown_max = _drawdown_from_equity(gains)

    cb_count = sum(1 for t in trades if _trade_is_defensive(t))

    combos = _pair_strategy_combos(trades)
    top_combos = combos[:3]
    bottom_combos = list(reversed(combos[-3:])) if combos else []

    return PortfolioInsights(
        period_start=period_start,
        period_end=period_end,
        total_trades=len(trades),
        total_pnl=total_pnl,
        total_fees=total_fees,
        net_pnl=total_pnl - total_fees,
        win_rate=win_rate,
        by_strategy=by_strategy,
        by_asset_concentration=shares,
        over_concentrated=over,
        eth_reserve_status=eth_status,
        drawdown_max=drawdown_max,
        recent_circuit_breaker_events=cb_count,
        top_pair_strategy=top_combos,
        bottom_pair_strategy=bottom_combos,
    )
