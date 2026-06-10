"""Follow large whale moves when risk rails and fee math allow (paper only)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable

import pandas as pd

from bot.adaptive import fee_floor_edge
from bot.strategies.base import TradeIntent
from bot.whale_watch import WhaleEvent

logger = logging.getLogger(__name__)

STRATEGY_NAME = "whale_follow"


@dataclass(frozen=True)
class WhaleFollowResult:
    intent: TradeIntent | None
    skip_reason: str = ""
    inferred_direction: str = ""


@dataclass
class WhaleFollowCooldown:
    """Per-asset cooldown and hourly follow cap."""

    cooldown_sec: int
    max_per_hour: int
    _last_follow_mono: dict[str, float]
    _hour_anchor: float
    _follows_this_hour: dict[str, int]

    def __init__(self, *, cooldown_sec: int, max_per_hour: int):
        self.cooldown_sec = max(0, cooldown_sec)
        self.max_per_hour = max(1, max_per_hour)
        self._last_follow_mono: dict[str, float] = {}
        self._hour_anchor = time.monotonic()
        self._follows_this_hour: dict[str, int] = {}

    def _roll_hour(self) -> None:
        now = time.monotonic()
        if now - self._hour_anchor >= 3600:
            self._hour_anchor = now
            self._follows_this_hour.clear()

    def can_follow(self, asset: str) -> tuple[bool, str]:
        self._roll_hour()
        now = time.monotonic()
        last = self._last_follow_mono.get(asset)
        if last is not None and self.cooldown_sec > 0:
            elapsed = now - last
            if elapsed < self.cooldown_sec:
                remain = int(self.cooldown_sec - elapsed)
                return False, f"cooldown ({remain}s remaining for {asset})"
        count = self._follows_this_hour.get(asset, 0)
        if count >= self.max_per_hour:
            return False, f"hourly cap ({self.max_per_hour}/hr for {asset})"
        return True, ""

    def record_follow(self, asset: str) -> None:
        self._roll_hour()
        self._last_follow_mono[asset] = time.monotonic()
        self._follows_this_hour[asset] = self._follows_this_hour.get(asset, 0) + 1


def infer_spike_direction(candles: pd.DataFrame | None) -> str:
    """Bullish/bearish from latest candle body; unknown if flat or no data."""
    if candles is None or candles.empty:
        return "unknown"
    latest = candles.iloc[-1]
    try:
        open_ = float(latest["open"])
        close = float(latest["close"])
    except (TypeError, ValueError, KeyError):
        return "unknown"
    if open_ <= 0:
        return "unknown"
    change = (close - open_) / open_
    if change >= 0.001:
        return "buy"
    if change <= -0.001:
        return "sell"
    return "unknown"


def infer_whale_direction(
    event: WhaleEvent,
    *,
    candles: pd.DataFrame | None = None,
) -> str:
    side = (event.direction or "").lower()
    if side in ("buy", "sell"):
        return side
    if side == "spike" or event.source == "volume_spike":
        return infer_spike_direction(candles)
    return "unknown"


def _momentum_gross(candles: pd.DataFrame | None) -> float:
    if candles is None or len(candles) < 2:
        return 0.0
    try:
        prev = float(candles.iloc[-2]["close"])
        last = float(candles.iloc[-1]["close"])
    except (TypeError, ValueError, KeyError):
        return 0.0
    if prev <= 0:
        return 0.0
    return abs(last - prev) / prev


def estimate_whale_follow_edge(
    event: WhaleEvent,
    *,
    candles: pd.DataFrame | None,
    fee_rate: float,
    hops: int = 1,
    min_usd: float,
) -> float:
    """Gross edge from whale conviction + short-term momentum (fee-aware floor)."""
    floor = fee_floor_edge(fee_rate, hops) * 1.15
    momentum = _momentum_gross(candles)
    conviction = min(0.015, max(0.0, (event.usd_size / max(min_usd, 1.0) - 1.0) * 0.001))
    return max(floor, momentum * 0.5 + conviction)


def resolve_follow_route(
    direction: str,
    asset: str,
    holdings: dict[str, float],
    find_path: Callable[[str, str], object | None],
) -> tuple[str, str] | None:
    if direction == "buy":
        if holdings.get("USD", 0.0) > 0 and find_path("USD", asset):
            return ("USD", asset)
        for src in ("ETH", "BTC"):
            if src != asset and holdings.get(src, 0.0) > 0 and find_path(src, asset):
                return (src, asset)
        return None
    if direction == "sell":
        if holdings.get(asset, 0.0) > 0 and find_path(asset, "USD"):
            return (asset, "USD")
        if asset not in ("ETH", "BTC") and holdings.get(asset, 0.0) > 0 and find_path(asset, "ETH"):
            return (asset, "ETH")
        return None
    return None


def build_whale_follow_reason(
    event: WhaleEvent,
    *,
    direction: str,
    from_asset: str,
    to_asset: str,
) -> str:
    label = event.source.replace("_", " ")
    if event.source == "volume_spike":
        return (
            f"whale-follow — {event.pair} {direction} on {label} "
            f"~${event.usd_size:,.0f} ({from_asset}->{to_asset})"
        )
    return (
        f"whale-follow — mirroring {event.pair} {event.direction} "
        f"${event.usd_size:,.0f} ({label})"
    )


def evaluate_whale_follow(
    event: WhaleEvent,
    *,
    holdings: dict[str, float],
    find_path: Callable[[str, str], object | None],
    candles: pd.DataFrame | None,
    size_pct: float,
    fee_rate: float,
    min_usd: float,
    cooldown: WhaleFollowCooldown,
) -> WhaleFollowResult:
    ok, reason = cooldown.can_follow(event.asset)
    if not ok:
        return WhaleFollowResult(None, skip_reason=reason)

    direction = infer_whale_direction(event, candles=candles)
    if direction not in ("buy", "sell"):
        return WhaleFollowResult(
            None,
            skip_reason="direction unclear (flat spike or unknown side)",
            inferred_direction=direction,
        )

    route = resolve_follow_route(direction, event.asset, holdings, find_path)
    if not route:
        return WhaleFollowResult(
            None,
            skip_reason=f"no holdings/path to follow {direction} on {event.asset}",
            inferred_direction=direction,
        )

    from_asset, to_asset = route
    path = find_path(from_asset, to_asset)
    hops = getattr(path, "hops", 1) if path else 1
    gross = estimate_whale_follow_edge(
        event, candles=candles, fee_rate=fee_rate, hops=hops, min_usd=min_usd
    )
    reason_text = build_whale_follow_reason(
        event, direction=direction, from_asset=from_asset, to_asset=to_asset
    )
    intent = TradeIntent(
        from_asset=from_asset,
        to_asset=to_asset,
        reason=reason_text,
        size_pct=max(0.01, min(1.0, size_pct)),
        edge=gross,
        gross_return_pct=gross,
        is_held_swap=from_asset != "USD" and to_asset != "USD",
        is_expansion=from_asset == "USD",
        strategy_name=STRATEGY_NAME,
    )
    return WhaleFollowResult(intent, inferred_direction=direction)


def format_whale_follow_alert(
    event: WhaleEvent,
    trade: dict,
    *,
    portfolio: float,
    baseline_pnl: float,
    inferred_direction: str,
) -> str:
    gain = float(trade.get("gain_loss", 0.0))
    size_pct = trade.get("size_pct")
    lines = [
        "**Whale-follow trade** 🐋",
        f"Signal: {event.pair} {event.direction} ~${event.usd_size:,.0f} ({event.source.replace('_', ' ')})",
        f"Action: mirrored **{inferred_direction}** — {trade.get('from_asset')} → {trade.get('to_asset')}",
        trade.get("reason", ""),
    ]
    if size_pct is not None:
        lines.append(f"Size: {float(size_pct):.0%} of {trade['from_asset']} (whale conviction sizing)")
    lines.extend([
        f"Fee: ${trade.get('fee_usd', 0):,.2f}  |  Gain/Loss: ${gain:+,.2f}",
        f"Portfolio ${portfolio:,.2f}  (PnL {baseline_pnl:+.2f} from start)",
    ])
    return "\n".join(lines)


def format_whale_follow_skip(event: WhaleEvent, reason: str) -> str:
    return (
        f"**Whale-follow skipped** — {event.pair} ${event.usd_size:,.0f}\n"
        f"Reason: {reason}"
    )
