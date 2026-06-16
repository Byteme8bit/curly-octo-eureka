"""Plain-text report formatting shared by terminal-adjacent surfaces (Discord)."""

from bot.live_portfolio import _SKIP_DISPLAY
from bot.local_time import format_pacific
from bot.status import StatusSnapshot
from bot.trade_log import (
    format_trade_route,
    pnl_label_for_trade,
    trade_narrative,
    trade_rationale,
)


def _holding_rows(
    holdings: dict[str, float],
    usd_prices: dict[str, float],
    *,
    skip_assets: frozenset[str] = frozenset(),
) -> list[tuple[float, str, float, float]]:
    rows: list[tuple[float, str, float, float]] = []
    for asset, qty in holdings.items():
        if qty <= 0 or asset in skip_assets:
            continue
        if asset == "USD":
            rows.append((qty, asset, qty, 1.0))
        else:
            price = usd_prices.get(asset, 0.0)
            rows.append((qty * price, asset, qty, price))
    rows.sort(reverse=True)
    return rows


def format_holdings(
    holdings: dict[str, float],
    usd_prices: dict[str, float],
    *,
    max_rows: int | None = None,
    skip_assets: frozenset[str] = frozenset(),
) -> list[str]:
    rows = _holding_rows(holdings, usd_prices, skip_assets=skip_assets)
    if max_rows is not None:
        rows = rows[:max_rows]
    lines: list[str] = []
    for value, asset, qty, price in rows:
        if asset == "USD":
            lines.append(f"  USD     ${qty:,.2f}  (cash)")
        else:
            lines.append(f"  {asset:6}  {qty:>12,.4f}  @ ${price:,.2f}  = ${value:,.2f}")
    if not rows:
        lines.append("  (empty)")
    elif max_rows is not None:
        total = len(_holding_rows(holdings, usd_prices, skip_assets=skip_assets))
        extra = total - max_rows
        if extra > 0:
            lines.append(f"  (+{extra} more)")
    return lines


def format_portfolio_command(
    *,
    portfolio: float,
    baseline_pnl: float,
    drawdown: float,
    holdings: dict[str, float],
    usd_prices: dict[str, float],
    trading_active: bool,
    risk_note: str = "",
    live_enabled: bool = False,
    mirror_mode: bool = False,
    live_portfolio: float | None = None,
    live_session_pnl: float | None = None,
    live_drawdown: float | None = None,
    live_holdings: dict[str, float] | None = None,
    max_holdings_rows: int = 5,
) -> str:
    """Discord ``TradeBot -portfolio`` body — live Kraken first when armed."""
    if not live_enabled:
        return format_portfolio_summary(
            portfolio=portfolio,
            baseline_pnl=baseline_pnl,
            drawdown=drawdown,
            holdings=holdings,
            usd_prices=usd_prices,
            trading_active=trading_active,
            risk_note=risk_note,
        )

    state = "RUNNING" if trading_active else "STOPPED"
    live_skip = _SKIP_DISPLAY

    if mirror_mode and live_portfolio is not None:
        lines = [
            "Live Kraken spot",
            (
                f"  Portfolio  ${live_portfolio:,.2f}  "
                f"(Session PnL {live_session_pnl:+.2f} | drawdown {live_drawdown:.2%})"
            ),
            "  Holdings:",
        ]
        lines.extend(
            format_holdings(
                live_holdings or {},
                usd_prices,
                max_rows=max_holdings_rows,
                skip_assets=live_skip,
            )
        )
        lines.extend(["", "[Paper sim] — not Kraken balance"])
        lines.append(
            f"  Portfolio  ${portfolio:,.2f}  (PnL {baseline_pnl:+.2f} | drawdown {drawdown:.2%})"
        )
        lines.append(f"  Bot state  {state}")
        if risk_note:
            lines.append(f"  {risk_note}")
        lines.append("  Holdings:")
        lines.extend(format_holdings(holdings, usd_prices, max_rows=max_holdings_rows))
        return "\n".join(lines)

    pnl_label = "Session PnL" if live_enabled else "PnL"
    lines = [
        "Live Kraken spot",
        (
            f"  Portfolio  ${portfolio:,.2f}  "
            f"({pnl_label} {baseline_pnl:+.2f} | drawdown {drawdown:.2%})"
        ),
        f"  Bot state  {state}",
    ]
    if risk_note:
        lines.append(f"  {risk_note}")
    lines.append("  Holdings:")
    lines.extend(
        format_holdings(holdings, usd_prices, max_rows=max_holdings_rows, skip_assets=live_skip)
    )
    return "\n".join(lines)


def format_considering(status: StatusSnapshot) -> list[str]:
    if status.considering:
        return [f"  • {line}" for line in status.considering[:5]]
    if status.idle_reason:
        return [f"  {status.idle_reason}"]
    return ["  (nothing queued)"]


def format_portfolio_summary(
    *,
    portfolio: float,
    baseline_pnl: float,
    drawdown: float,
    holdings: dict[str, float],
    usd_prices: dict[str, float],
    trading_active: bool,
    risk_note: str = "",
) -> str:
    state = "RUNNING" if trading_active else "STOPPED"
    lines = [
        f"Portfolio  ${portfolio:,.2f}  (PnL {baseline_pnl:+.2f} | drawdown {drawdown:.2%})",
        f"Bot state  {state}",
    ]
    if risk_note:
        lines.append(risk_note)
    lines.append("")
    lines.append("Holdings:")
    lines.extend(format_holdings(holdings, usd_prices))
    return "\n".join(lines)


def format_planned_actions(status: StatusSnapshot, *, status_since: str | None = None) -> str:
    lines = ["Planned actions / considering:"]
    lines.extend(format_considering(status))
    if status_since and status.mode == "hold":
        lines.append("")
        lines.append(f"Last change: {status_since}")
    return "\n".join(lines)


def format_trade_block(trades: list[dict]) -> str:
    lines = ["TRADE EXECUTED"]
    for trade in trades:
        lines.append(f"  {trade_narrative(trade)}")
        lines.append(f"  {format_trade_route(trade)}")
        lines.append(
            f"  Fee: ${trade.get('fee_usd', 0):,.2f}  |  "
            f"Gain/Loss: {pnl_label_for_trade(trade)}"
        )
    return "\n".join(lines)


def format_discord_tick(
    *,
    portfolio: float,
    baseline_pnl: float,
    drawdown: float,
    holdings: dict[str, float],
    usd_prices: dict[str, float],
    trades: list[dict],
    status: StatusSnapshot,
    status_changed: bool,
    status_since: str | None,
    trading_active: bool,
    risk_note: str = "",
    elapsed: float = 0.0,
    poll_interval: int = 15,
) -> tuple[str, str]:
    """Return (title, body) for a Discord status post."""
    now = format_pacific()

    if trades:
        title = "TRADE"
        body = format_portfolio_summary(
            portfolio=portfolio,
            baseline_pnl=baseline_pnl,
            drawdown=drawdown,
            holdings=holdings,
            usd_prices=usd_prices,
            trading_active=trading_active,
            risk_note=risk_note,
        )
        body += "\n\n" + format_trade_block(trades)
        return title, body

    if status_changed or status_since is None:
        title = "PORTFOLIO" if status.mode != "paused" else "HIBERNATING"
        body = format_portfolio_summary(
            portfolio=portfolio,
            baseline_pnl=baseline_pnl,
            drawdown=drawdown,
            holdings=holdings,
            usd_prices=usd_prices,
            trading_active=trading_active,
            risk_note=risk_note,
        )
        if status.mode in ("hold", "paused"):
            body += "\n\nConsidering:\n" + "\n".join(format_considering(status))
        body += f"\n\n{now}  |  fetch {elapsed:.1f}s"
        return title, body

    since = status_since or now
    title = "Holding pattern"
    preview = status.considering[0] if status.considering else status.idle_reason or "HOLD"
    if status.considering and len(status.considering) > 1:
        preview += f" (+{len(status.considering) - 1} more)"
    body = (
        f"No changes since {since}\n"
        f"Portfolio ${portfolio:,.2f}  (PnL {baseline_pnl:+.2f})\n"
        f"Still watching: {preview}"
    )
    if risk_note:
        body += f"\n{risk_note}"
    return title, body


def pnl_milestone_band(baseline_pnl: float, baseline_portfolio: float, threshold_pct: float) -> int:
    """Integer band for gain/loss milestones (0 = within threshold)."""
    if baseline_portfolio <= 0 or threshold_pct <= 0:
        return 0
    pnl_pct = baseline_pnl / baseline_portfolio
    if abs(pnl_pct) < threshold_pct:
        return 0
    if pnl_pct >= 0:
        return int(pnl_pct // threshold_pct)
    return -int((-pnl_pct) // threshold_pct)


def format_trade_executed_alert(
    trade: dict,
    portfolio: float,
    baseline_pnl: float,
    *,
    verify_tag: str = "",
) -> str:
    gain = float(trade.get("gain_loss", 0.0))
    size_pct = trade.get("size_pct")
    headline = "**LIVE trade executed**" if trade.get("live") else "**Trade executed**"
    lines = [
        headline,
        trade_narrative(trade),
        trade_rationale(trade),
        format_trade_route(trade),
    ]
    if size_pct is not None:
        lines.append(f"Size: {float(size_pct):.0%} of {trade['from_asset']}")
    lines.extend([
        f"Fee: ${trade.get('fee_usd', 0):,.2f}  |  "
        f"Gain/Loss: {pnl_label_for_trade(trade)}",
        f"Portfolio ${portfolio:,.2f}  (PnL {baseline_pnl:+.2f} from start)",
    ])
    if verify_tag:
        lines.append(f"_{verify_tag}_")
    return "\n".join(lines)


def format_major_trade_alert(trade: dict, portfolio: float, baseline_pnl: float) -> str:
    gain = trade.get("gain_loss", 0.0)
    direction = "gain" if gain >= 0 else "loss"
    body = format_trade_executed_alert(trade, portfolio, baseline_pnl)
    return body.replace("**Trade executed**", f"**Major trade {direction} — ${abs(gain):,.2f}**", 1)


def format_pnl_milestone_alert(
    portfolio: float,
    baseline_pnl: float,
    baseline_portfolio: float,
    *,
    band: int,
    threshold_pct: float,
    source: str = "paper",
) -> str:
    pnl_pct = (baseline_pnl / baseline_portfolio * 100) if baseline_portfolio > 0 else 0.0
    if band > 0:
        headline = f"**Major portfolio gain — {pnl_pct:+.1f}%**"
    else:
        headline = f"**Major portfolio loss — {pnl_pct:+.1f}%**"
    if source == "live":
        portfolio_line = (
            f"Live Kraken spot: ${portfolio:,.2f}  |  "
            f"Session PnL: ${baseline_pnl:+,.2f}"
        )
    else:
        portfolio_line = (
            f"[Paper sim] Portfolio ${portfolio:,.2f}  |  "
            f"PnL {baseline_pnl:+.2f} from start"
        )
    return (
        f"{headline}\n"
        f"{portfolio_line}\n"
        f"Crossed {abs(band) * threshold_pct:.0%} milestone (threshold {threshold_pct:.0%} per pin)"
    )


STRATEGY_DESCRIPTIONS: dict[str, str] = {
    "cross_momentum": "Cross-pair relative momentum (15m/1h EMA + RVOL)",
    "triangular_arbitrage": "Triangular arbitrage (3-leg cross-pair loops)",
    "stat_arb": "Statistical arbitrage (Z-score mean reversion)",
    "momentum_rotation": "Momentum rotation (single-strategy legacy)",
    "equity_dca": "Equity DCA — scheduled USD buys into xStocks/ETFs",
    "hold": "Hold — no trades (data-feed test mode)",
    "orchestrator": "Multi-strategy orchestrator",
    "whale_follow": "Whale follow — mirror large moves when rails allow",
}


def format_strategy_status(
    *,
    configured: tuple[str, ...],
    active_names: list[str],
    last_result=None,
    governor_status=None,
    governor_summary: str = "",
) -> str:
    """Discord/terminal summary of loaded plugins and current trade focus."""
    lines = ["**Active strategies** (`STRATEGIES` env):"]
    for name in active_names:
        desc = STRATEGY_DESCRIPTIONS.get(name, name.replace("_", " "))
        lines.append(f"• `{name}` — {desc}")

    if tuple(active_names) != configured:
        lines.append("")
        lines.append(f"_Configured:_ `{', '.join(configured)}`")

    lines.append("")
    lines.append("**Current focus**")

    if last_result is None:
        lines.append("• Awaiting first market tick")
        return "\n".join(lines)

    if last_result.intents:
        top = last_result.intents[0]
        strategy = top.strategy_name or "unknown"
        lines.append(f"• **`{strategy}`** — {top.from_asset} → {top.to_asset}")
        lines.append(f"  {top.reason}")
        if top.edge or top.gross_return_pct:
            edge = top.gross_return_pct or top.edge
            lines.append(f"  Edge: {edge:+.4f} (pre-fee estimate)")
        if len(last_result.intents) > 1:
            others = ", ".join(
                f"`{i.strategy_name}`" for i in last_result.intents[1:4] if i.strategy_name
            )
            if others:
                lines.append(f"  Also ranked: {others}")
    elif last_result.opportunities:
        top = last_result.opportunities[0]
        lines.append(
            f"• Scanning — best opportunity: {top.from_asset} → {top.to_asset} "
            f"({top.category}, edge {top.edge:+.4f})"
        )
    elif last_result.idle_reason:
        lines.append(f"• {last_result.idle_reason}")
    else:
        lines.append("• Monitoring — no trade signal this tick")

    if last_result.leader:
        lines.append("")
        lines.append(f"**Momentum leader:** `{last_result.leader}`")

    if governor_summary:
        lines.append("")
        lines.append(governor_summary)

    if governor_status and governor_status.notes:
        lines.append("")
        lines.append("**Policy this tick:**")
        for note in governor_status.notes:
            lines.append(f"• {note}")

    return "\n".join(lines)
