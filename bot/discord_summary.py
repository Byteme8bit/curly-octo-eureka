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


def format_live_mirror_skip_alert(
    trade: dict,
    reason: str,
    *,
    verify_tag: str = "",
    net_pct: float | None = None,
) -> str:
    route = f"{trade.get('from_asset', '?')}→{trade.get('to_asset', '?')}"
    net_line = ""
    if net_pct is not None:
        net_line = f" est. net **{net_pct:+.4%}** after fees —"
    tag = f" ({verify_tag})" if verify_tag else ""
    return (
        f"**Live mirror skipped** — `{route}`{tag}\n"
        f"{net_line} {reason}"
    )


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
    live_portfolio: float | None = None,
    live_session_pnl: float | None = None,
    best_live_route: str = "",
    best_live_route_net_pct: float | None = None,
    live_skip_reason: str = "",
) -> str:
    lines = [
        "**TradeBot hourly summary**",
    ]
    if live_portfolio is not None and live_session_pnl is not None:
        lines.append(
            f"**Live Kraken spot:** ${live_portfolio:,.2f}  |  "
            f"Session PnL: ${live_session_pnl:+,.2f}"
        )
        if best_live_route and best_live_route_net_pct is not None:
            lines.append(
                f"Best single-hop route: `{best_live_route}` "
                f"gross edge {best_live_route_net_pct:+.4%} (taker fees still apply)"
            )
        if live_skip_reason:
            short = live_skip_reason[:140] + ("…" if len(live_skip_reason) > 140 else "")
            lines.append(f"No live fill yet: {short}")
    lines.extend([
        f"Paper trades (hour): {trade_count}  |  Net PnL: ${net_pnl:+,.2f}",
        f"Blocked attempts: {blocked_count}",
    ])
    if top_block_reason:
        short = top_block_reason[:120] + ("…" if len(top_block_reason) > 120 else "")
        lines.append(f"Top block reason: {short}")
    if live_portfolio is not None and live_session_pnl is not None:
        lines.append(
            f"[Paper sim] Portfolio ${portfolio:,.2f}  (PnL {baseline_pnl:+.2f} from start)"
        )
    else:
        lines.append(f"Portfolio ${portfolio:,.2f}  (PnL {baseline_pnl:+.2f} from start)")
    if primary_goal_headline and primary_goal_progress_pct is not None:
        lines.append(f"Primary goal: {primary_goal_headline} ({primary_goal_progress_pct:.1f}%)")
    elif tier_label:
        lines.append(f"Goal tier: {tier_label}")
    if crash_hold:
        lines.append("Crash hold: **active**")
    return "\n".join(lines)


def format_tick_activity_line(
    *,
    last_scan_at: str,
    opportunity_count: int,
    top_block_reason: str = "",
    poll_interval: int = 15,
    idle_hours: float = 0.0,
    paper_trades_session: int = 0,
    live_trades_session: int = 0,
    live_halted: bool = False,
    live_halt_reason: str = "",
) -> str:
    """One-line scan summary for heartbeat / portfolio when Discord is quiet."""
    idle_min = int(round(idle_hours * 60))
    parts = [
        f"Last scan {last_scan_at} (every {poll_interval}s)",
        f"{opportunity_count} routes scored",
        f"paper {paper_trades_session} live {live_trades_session} this session",
    ]
    if idle_min > 0:
        parts.append(f"idle {idle_min}m since last trade")
    if live_halted:
        short = (live_halt_reason or "halted")[:80]
        parts.append(f"LIVE HALTED: {short}")
    elif top_block_reason:
        short = top_block_reason[:100] + ("…" if len(top_block_reason) > 100 else "")
        parts.append(f"top block: {short}")
    return "Scan activity — " + " | ".join(parts)


def format_futures_trade_alert(trade: dict, *, paper: bool = True) -> str:
    """Discord alert for a futures paper or live open/close."""
    action = str(trade.get("action") or "").lower()
    symbol = str(trade.get("symbol") or "?")
    side = str(trade.get("side") or "?").upper()
    reason = str(trade.get("reason") or "")
    mode = "paper" if paper or trade.get("paper", paper) else "LIVE"
    if action == "open":
        price = float(trade.get("price") or 0.0)
        margin = float(trade.get("margin_usd") or 0.0)
        lev = float(trade.get("leverage") or 0.0)
        return (
            f"**Futures {mode} OPEN** — {side} {symbol} @ ${price:,.4f} "
            f"| margin ${margin:,.0f} @ {lev:.0f}x | {reason}"
        )
    pnl = float(trade.get("pnl_usd") or 0.0)
    return (
        f"**Futures {mode} CLOSE** — {symbol} {side} "
        f"| PnL ${pnl:+,.2f} | {reason}"
    )


def format_futures_positions_summary(
    positions: dict,
    *,
    balance_usd: float,
    paper: bool = True,
) -> str:
    """Compact multi-line summary of open futures positions."""
    if not positions:
        mode = "paper" if paper else "live"
        return f"Futures ({mode}): flat — wallet ${balance_usd:,.2f}"
    lines = [f"Futures ({'paper' if paper else 'live'}) wallet ${balance_usd:,.2f}:"]
    for sym, pos in sorted(positions.items()):
        side = str(getattr(pos, "side", None) or (pos.get("side") if isinstance(pos, dict) else "?"))
        entry = float(
            getattr(pos, "entry_price", None)
            or (pos.get("entry_price") if isinstance(pos, dict) else 0.0)
            or 0.0
        )
        margin = float(
            getattr(pos, "margin_usd", None)
            or (pos.get("margin_usd") if isinstance(pos, dict) else 0.0)
            or 0.0
        )
        short_sym = sym.split(":")[0] if ":" in sym else sym
        lines.append(f"• {side.upper()} {short_sym} @ ${entry:,.4f} (margin ${margin:,.0f})")
    return "\n".join(lines)
