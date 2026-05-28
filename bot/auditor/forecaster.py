"""PnL forecasting with confidence bands.

The model deliberately stays simple: trade-rate extrapolation for medium
samples, and a bootstrap resample for larger samples. We never claim
predictive certainty; horizons that the data cannot support are dropped.
Stdlib only (`statistics`, `random`).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from statistics import mean, pstdev

from bot.auditor.analyzer import PortfolioInsights


@dataclass(frozen=True)
class ForecastBand:
    horizon: str            # "24h" | "7d" | "30d"
    expected_pnl: float
    lower_band: float       # ~10th percentile
    upper_band: float       # ~90th percentile
    confidence: float       # 0..1
    method: str             # "insufficient_data" | "trade_rate_extrapolation" | "bootstrap"


_HORIZON_HOURS = {"24h": 24.0, "7d": 24.0 * 7, "30d": 24.0 * 30}


def _trade_rate_per_hour(trades: list[dict]) -> float:
    """Observed trade rate using the first/last trade timestamps.

    Falls back to a tiny floor (one trade per day) so downstream math doesn't
    divide by zero when the window is degenerate.
    """
    if len(trades) < 2:
        return 1.0 / 24.0
    try:
        first = datetime.fromisoformat(str(trades[0].get("time", "")).replace("Z", "+00:00"))
        last = datetime.fromisoformat(str(trades[-1].get("time", "")).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return 1.0 / 24.0
    hours = max(1.0 / 60.0, (last - first).total_seconds() / 3600.0)
    return len(trades) / hours


def _net_outcomes(trades: list[dict]) -> list[float]:
    return [
        float(t.get("gain_loss", 0.0)) - float(t.get("fee_usd", 0.0))
        for t in trades
    ]


def _confidence_for(n: int, horizon_hours: float) -> float:
    """Confidence shrinks as horizon stretches and grows with data volume."""
    if n <= 0:
        return 0.0
    sample_score = min(1.0, n / 200.0)         # 200 trades -> full sample score
    horizon_decay = 24.0 / (24.0 + horizon_hours)  # 24h -> 0.5; 30d -> 0.032
    return round(max(0.0, min(1.0, sample_score * horizon_decay * 1.5)), 4)


def _insufficient_band(horizon: str) -> ForecastBand:
    return ForecastBand(
        horizon=horizon,
        expected_pnl=0.0,
        lower_band=0.0,
        upper_band=0.0,
        confidence=0.0,
        method="insufficient_data",
    )


def _trade_rate_band(
    horizon: str,
    rate_per_hour: float,
    net_outcomes: list[float],
) -> ForecastBand:
    hours = _HORIZON_HOURS[horizon]
    avg = mean(net_outcomes) if net_outcomes else 0.0
    sigma = pstdev(net_outcomes) if len(net_outcomes) > 1 else abs(avg) * 0.5
    expected_trades = rate_per_hour * hours
    expected = avg * expected_trades
    # Spread = ~1.28 sigma * sqrt(N) for ~80% interval. Inflate by 1.5x for honesty.
    spread = 1.92 * sigma * (max(0.0, expected_trades) ** 0.5)
    return ForecastBand(
        horizon=horizon,
        expected_pnl=expected,
        lower_band=expected - spread,
        upper_band=expected + spread,
        confidence=_confidence_for(len(net_outcomes), hours),
        method="trade_rate_extrapolation",
    )


def _bootstrap_band(
    horizon: str,
    rate_per_hour: float,
    net_outcomes: list[float],
    *,
    iterations: int = 500,
    seed: int | None = None,
) -> ForecastBand:
    hours = _HORIZON_HOURS[horizon]
    expected_trades = max(1, int(round(rate_per_hour * hours)))
    rng = random.Random(seed if seed is not None else 1337)
    sums = []
    for _ in range(iterations):
        sample_sum = 0.0
        for _i in range(expected_trades):
            sample_sum += rng.choice(net_outcomes)
        sums.append(sample_sum)
    sums.sort()

    def pct(p: float) -> float:
        idx = max(0, min(len(sums) - 1, int(round(p * (len(sums) - 1)))))
        return sums[idx]

    return ForecastBand(
        horizon=horizon,
        expected_pnl=mean(sums),
        lower_band=pct(0.10),
        upper_band=pct(0.90),
        confidence=_confidence_for(len(net_outcomes), hours),
        method="bootstrap",
    )


def forecast_pnl(
    insights: PortfolioInsights,
    trades: list[dict],
    *,
    bootstrap_iterations: int = 500,
    seed: int | None = None,
) -> list[ForecastBand]:
    """Return forecast bands for the horizons supported by data volume.

    Rules (honest math):
    - <10 trades: single 24h `insufficient_data` band.
    - 10-50 trades: 24h + 7d `trade_rate_extrapolation`.
    - >50 trades: 24h + 7d + 30d `bootstrap` resample.
    """
    n = insights.total_trades
    if n < 10:
        return [_insufficient_band("24h")]

    rate = _trade_rate_per_hour(trades)
    outcomes = _net_outcomes(trades) or [0.0]

    if n <= 50:
        return [
            _trade_rate_band("24h", rate, outcomes),
            _trade_rate_band("7d", rate, outcomes),
        ]

    return [
        _bootstrap_band("24h", rate, outcomes, iterations=bootstrap_iterations, seed=seed),
        _bootstrap_band("7d", rate, outcomes, iterations=bootstrap_iterations, seed=seed),
        _bootstrap_band("30d", rate, outcomes, iterations=bootstrap_iterations, seed=seed),
    ]
