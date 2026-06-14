"""TradeBot hourly Discord summary and major-market-move alerts."""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class TradeActivityBuffer:
    """In-memory rolling window of trade/blocked events for hourly summaries."""

    window_seconds: float = 3600.0
    trades: list[dict] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)

    def record_trades(self, trades: list[dict]) -> None:
        if not trades:
            return
        now = time.time()
        for trade in trades:
            self.trades.append({"at": now, "trade": trade})

    def record_blocked(self, blocked: list[str]) -> None:
        if not blocked:
            return
        now = time.time()
        for reason in blocked:
            self.blocked.append({"at": now, "reason": reason})

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        self.trades = [e for e in self.trades if e["at"] >= cutoff]
        self.blocked = [e for e in self.blocked if e["at"] >= cutoff]

    def snapshot(self) -> dict:
        now = time.time()
        self._prune(now)
        net_pnl = sum(float(e["trade"].get("gain_loss", 0)) for e in self.trades)
        block_counts = Counter(e["reason"] for e in self.blocked)
        top_block = block_counts.most_common(1)[0][0] if block_counts else ""
        return {
            "trade_count": len(self.trades),
            "net_pnl": net_pnl,
            "blocked_count": len(self.blocked),
            "top_block_reason": top_block,
        }


@dataclass
class MajorMoveTracker:
    """Post once per asset when 1h price move exceeds threshold."""

    threshold_pct: float
    cooldown_seconds: float
    _baseline_prices: dict[str, float] = field(default_factory=dict)
    _last_alert_at: dict[str, float] = field(default_factory=dict)

    def check(self, asset: str, price: float, *, now: float | None = None) -> str | None:
        if price <= 0 or self.threshold_pct <= 0:
            return None
        anchor = now if now is not None else time.time()
        base = self._baseline_prices.get(asset)
        if base is None or base <= 0:
            self._baseline_prices[asset] = price
            return None
        move = (price - base) / base
        if abs(move) < self.threshold_pct:
            return None
        last = self._last_alert_at.get(asset, 0.0)
        if anchor - last < self.cooldown_seconds:
            return None
        self._last_alert_at[asset] = anchor
        self._baseline_prices[asset] = price
        direction = "up" if move >= 0 else "down"
        return (
            f"**Major market move — {asset}** {direction} {abs(move):.1%} "
            f"vs ~1h ago (${base:,.4f} → ${price:,.4f})"
        )

    def refresh_baselines(self, usd_prices: dict[str, float], *, now: float | None = None) -> None:
        """Decay baselines toward current prices so moves are measured over ~1h."""
        anchor = now if now is not None else time.time()
        alpha = min(1.0, 60.0 / max(60.0, self.cooldown_seconds))
        for asset, price in usd_prices.items():
            if asset == "USD" or price <= 0:
                continue
            prev = self._baseline_prices.get(asset)
            if prev is None:
                self._baseline_prices[asset] = price
            else:
                self._baseline_prices[asset] = prev + alpha * (price - prev)
        _ = anchor


def format_hourly_summary(
    *,
    trade_count: int,
    net_pnl: float,
    blocked_count: int,
    top_block_reason: str,
    portfolio: float,
    baseline_pnl: float,
    tier_label: str = "",
    crash_hold: bool = False,
    primary_goal_headline: str = "",
    primary_goal_progress_pct: float | None = None,
) -> str:
    lines = [
        "**TradeBot hourly summary**",
        f"Trades: {trade_count}  |  Net PnL (hour): ${net_pnl:+,.2f}",
        f"Blocked attempts: {blocked_count}",
    ]
    if top_block_reason:
        short = top_block_reason[:120] + ("…" if len(top_block_reason) > 120 else "")
        lines.append(f"Top block reason: {short}")
    lines.append(f"Portfolio ${portfolio:,.2f}  (PnL {baseline_pnl:+.2f} from start)")
    if primary_goal_headline and primary_goal_progress_pct is not None:
        lines.append(f"Primary goal: {primary_goal_headline} ({primary_goal_progress_pct:.1f}%)")
    elif tier_label:
        lines.append(f"Goal tier: {tier_label}")
    if crash_hold:
        lines.append("Crash hold: **active**")
    return "\n".join(lines)
