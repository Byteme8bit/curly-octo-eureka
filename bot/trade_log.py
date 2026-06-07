from pathlib import Path

from bot.local_time import (
    format_log_window_range,
    format_pacific,
    log_window_bounds,
    log_window_filename,
    pacific_now,
    pacific_stamp,
)
from bot.status import StatusSnapshot
from config import SYMBOL_ASSETS


def _usd_momentum_ranking(scores: dict[str, float]) -> list[tuple[str, float]]:
    """Rank momentum scores — only USD pair symbols (excludes stat-arb ratio keys)."""
    items = [(symbol, score) for symbol, score in scores.items() if symbol in SYMBOL_ASSETS]
    return sorted(items, key=lambda item: item[1], reverse=True)


def format_rotation_option(option, find_path_fn) -> str:
    """Plain-English rotation line with route and fee hurdle."""
    labels = {
        "held_swap": "Held swap",
        "expansion": "Expansion",
        "diversify": "Diversify",
        "leader_rotation": "Leader rotation",
        "rotation": "Rotation",
    }
    label = labels.get(option.category, "Rotation")

    if option.path:
        route_note = f" via {option.path.replace('->', ' -> ')}"
        if option.hops > 1:
            route_note += f" ({option.hops} hops)"
    else:
        route = find_path_fn(option.from_asset, option.to_asset) if find_path_fn else None
        if route:
            route_note = f" via {route.path.replace('->', ' -> ')}"
            if route.hops > 1:
                route_note += f" ({route.hops} hops)"
        elif option.to_asset == "USD" or option.from_asset == "USD":
            route_note = " via USD pair"
        else:
            route_note = " (no route found)"

    if option.edge >= option.required_edge:
        status = "meets fee hurdle"
    else:
        status = "below fee hurdle"

    return (
        f"  {label}: {option.from_asset} -> {option.to_asset}  "
        f"(edge {option.edge:+.4f}, need {option.required_edge:+.4f}, {status})"
        f"{route_note}"
    )


def format_trade_route(trade: dict) -> str:
    if trade.get("type") != "multi_hop":
        return f"Pair: {trade['symbol']} ({trade.get('type', 'usd')})"

    legs = trade.get("legs", [])
    leg_summary = ", ".join(f"{t['symbol']}" for t in legs)
    return (
        f"Route: {trade.get('path', '').replace('->', ' -> ')} "
        f"({trade.get('hops', 1)} hops via {leg_summary})"
    )


def format_qty(asset: str, qty: float) -> str:
    if asset == "USD":
        return f"${qty:,.2f}"
    if qty >= 1:
        return f"{qty:,.4f} {asset}"
    return f"{qty:.6f} {asset}"


def trade_narrative(trade: dict) -> str:
    """Plain-English one-liner for logs and receipts."""
    from_a = trade["from_asset"]
    to_a = trade["to_asset"]
    from_qty = trade.get("from_qty", 0)
    to_qty = trade.get("to_qty", 0)
    reason = trade.get("reason", "No reason given")
    return f"Traded {format_qty(from_a, from_qty)} to {format_qty(to_a, to_qty)} because {reason}"


def classify_trade(trade: dict) -> str:
    """Answer the user's question: was this loss-mitigation or going for growth?

    Returns a short, human label describing the *intent* behind a fill, derived
    from the flags the strategy/engine attached to the trade dict.
    """
    if trade.get("is_defensive"):
        return "LOSS-MITIGATION (defensive de-risking)"
    gain = float(trade.get("gain_loss", 0.0))
    side = trade.get("side", "buy")
    if side == "sell" and trade.get("to_asset") == "USD":
        if gain > 0:
            return "PROFIT-TAKING (locking in a gain)"
        if gain < 0:
            return "LOSS-MITIGATION (cutting a losing position)"
        return "EXIT (flat)"
    if trade.get("is_expansion"):
        return "GROWTH (opening a new position)"
    if trade.get("is_held_swap") or trade.get("type") in ("cross", "multi_hop"):
        return "REBALANCE (rotating into stronger momentum)"
    return "GROWTH (adding to a position)"


def _edge_str(trade: dict) -> str:
    """Format the captured edge as a percentage, preferring gross then net."""
    edge = trade.get("gross_return_pct") or trade.get("edge")
    if not edge:
        return ""
    return f"{float(edge):+.2%}"


def trade_rationale(trade: dict) -> str:
    """Multi-line 'why' block for Discord/terminal.

    Spells out the intent class (growth vs loss-mitigation), which strategy
    fired, the expected edge, and the underlying reason string.
    """
    lines = [f"Why: {classify_trade(trade)}"]
    strat = trade.get("strategy_name") or "unknown"
    edge = _edge_str(trade)
    detail = f"Strategy: `{strat}`"
    if edge:
        detail += f"  |  Expected edge: {edge}"
    lines.append(detail)
    reason = trade.get("reason")
    if reason:
        lines.append(f"Signal: {reason}")
    return "\n".join(lines)


def pnl_label(gain_loss: float, side: str, trade_type: str = "") -> str:
    """Format gain/loss for display.

    USD buys with zero realized PnL are labeled ``(entry)``. Cross-coin swaps
    use USD mark-to-mark at execution time (see ``paper_broker``).
    """
    if gain_loss > 0:
        return f"+${gain_loss:.2f} (profit)"
    if gain_loss < 0:
        return f"-${abs(gain_loss):.2f} (loss)"
    if side == "buy" and trade_type not in ("cross", "multi_hop"):
        return "$0.00 (entry)"
    if trade_type == "cross":
        return "$0.00 (swap)"
    return "$0.00 (break-even)"


def pnl_label_for_trade(trade: dict) -> str:
    return pnl_label(
        float(trade.get("gain_loss", 0.0)),
        trade.get("side", "buy"),
        trade.get("type", ""),
    )


class BotFileLogger:
    """Human-readable logs in logs/, rotated every N hours (Pacific time)."""

    def __init__(self, log_dir: Path, rotate_hours: int = 4):
        from bot.structured_log import StructuredLogger  # avoid circular import at module level
        self.log_dir = log_dir
        self.rotate_hours = rotate_hours
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._window_start = None
        self._window_end = None
        self.log_file: Path | None = None
        self._last_status_key: str | None = None
        self._status_since: str | None = None
        self._structured = StructuredLogger(log_dir)
        self._ensure_log_file()

    def _ensure_log_file(self) -> None:
        now = pacific_now()
        start, end = log_window_bounds(now, self.rotate_hours)
        if self._window_start == start and self.log_file is not None:
            return

        self._window_start = start
        self._window_end = end
        self.log_file = self.log_dir / log_window_filename(start, end)

        if not self.log_file.exists():
            header = (
                "Bot session log\n"
                f"Window: {format_log_window_range(start, end)}\n"
                f"{'=' * 50}\n"
            )
            with open(self.log_file, "w", encoding="utf-8") as f:
                f.write(header)

    def current_log_file(self) -> Path:
        self._ensure_log_file()
        assert self.log_file is not None
        return self.log_file

    def _write(self, text: str) -> None:
        with open(self.current_log_file(), "a", encoding="utf-8") as f:
            f.write(text)

    def log_tick(
        self,
        portfolio: float,
        baseline_pnl: float,
        drawdown: float,
        result,
        holdings: dict[str, float],
        usd_prices: dict[str, float],
        blocked: list[str],
        trades: list[dict],
        status: StatusSnapshot,
        status_changed: bool,
        status_since: str | None,
        find_path_fn=None,
    ) -> None:
        now = format_pacific()

        if trades or status_changed or self._last_status_key is None:
            self._write_full_tick(
                now=now,
                portfolio=portfolio,
                baseline_pnl=baseline_pnl,
                drawdown=drawdown,
                result=result,
                holdings=holdings,
                usd_prices=usd_prices,
                blocked=blocked,
                trades=trades,
                status=status,
                find_path_fn=find_path_fn,
            )
        else:
            since = status_since or self._status_since or now
            preview = status.considering[0] if status.considering else status.idle_reason or "HOLD"
            if status.considering and len(status.considering) > 1:
                preview += f" (+{len(status.considering) - 1} more)"
            self._write(
                f"[{now}] No changes since {since} — HOLD — "
                f"portfolio ${portfolio:,.2f} (PnL {baseline_pnl:+.2f}) — "
                f"watching: {preview}\n"
            )

        # Emit JSONL records for every filled trade so external tools can
        # consume events.jsonl without parsing the human-readable log.
        for trade in trades:
            self._structured.log_trade(trade)

        self._last_status_key = status.summary_key
        if status_changed or trades:
            self._status_since = now

    def _write_full_tick(
        self,
        *,
        now: str,
        portfolio: float,
        baseline_pnl: float,
        drawdown: float,
        result,
        holdings: dict[str, float],
        usd_prices: dict[str, float],
        blocked: list[str],
        trades: list[dict],
        status: StatusSnapshot,
        find_path_fn=None,
    ) -> None:
        ranked = _usd_momentum_ranking(result.scores)
        if ranked:
            leader_sym, leader_score = ranked[0]
            leader = SYMBOL_ASSETS[leader_sym]
        else:
            leader, leader_score = "—", 0.0

        lines = [
            "",
            "=" * 50,
            f"MARKET CHECK - {now}",
            "=" * 50,
            f"Portfolio:  ${portfolio:,.2f}  (PnL {baseline_pnl:+.2f} | drawdown {drawdown:.2%})",
            "",
            "Holdings:",
        ]

        if holdings.get("USD", 0) > 0:
            lines.append(f"  {format_qty('USD', holdings['USD'])}")
        held = [a for a, q in holdings.items() if a != "USD" and q > 0]
        for asset in sorted(held):
            qty = holdings[asset]
            usd_val = qty * usd_prices.get(asset, 0)
            lines.append(f"  {format_qty(asset, qty)}  (${usd_val:,.2f})")

        if not held and holdings.get("USD", 0) <= 0:
            lines.append("  (empty)")

        portfolio_val = holdings.get("USD", 0.0)
        for asset, qty in holdings.items():
            if asset != "USD" and qty > 0:
                portfolio_val += qty * usd_prices.get(asset, 0)

        if held and portfolio_val > 0:
            lines.append("")
            lines.append("Allocation:")
            for asset in sorted(held):
                pct = (holdings[asset] * usd_prices.get(asset, 0)) / portfolio_val
                lines.append(f"  {asset}: {pct:.1%}")

        lines.extend(
            [
                "",
                f"Market leader: {leader} ({leader_score:+.4f})",
                "",
                "Momentum:",
            ]
        )
        for i, (symbol, score) in enumerate(ranked, 1):
            asset = SYMBOL_ASSETS[symbol]
            marker = " *" if asset in held else ""
            lines.append(f"  {i:2}. {asset:6}  {score:+.4f}{marker}")

        if trades:
            lines.append("")
            lines.append("Decision: TRADE")
            for trade in trades:
                lines.append(f"  {trade_narrative(trade)}")
                lines.append(f"  {format_trade_route(trade)}")
                lines.append(
                    f"  Fee: ${trade.get('fee_usd', 0):.2f}  |  "
                    f"Gain/Loss: {pnl_label_for_trade(trade)}"
                )
        else:
            lines.append("")
            lines.append("Decision: HOLD")
            if result.idle_reason:
                lines.append(f"  {result.idle_reason}")
            if status.considering:
                lines.append("")
                lines.append("Considering:")
                for line in status.considering:
                    lines.append(f"  {line}")

        extra_blocked = [n for n in blocked if n != result.idle_reason]
        if extra_blocked:
            lines.append("")
            lines.append("Risk gate:")
            for note in extra_blocked:
                lines.append(f"  {note}")

        if result.opportunities and not trades and find_path_fn:
            lines.append("")
            lines.append("Rotation options:")
            seen: set[str] = set()
            for option in result.opportunities:
                key = f"{option.from_asset}->{option.to_asset}:{option.category}"
                if key in seen:
                    continue
                seen.add(key)
                lines.append(format_rotation_option(option, find_path_fn))

        lines.append("")
        self._write("\n".join(lines) + "\n")


class ReceiptWriter:
    """Plain-text trade receipts in receipts/."""

    def __init__(self, receipts_dir: Path):
        self.receipts_dir = receipts_dir
        self.receipts_dir.mkdir(parents=True, exist_ok=True)

    def save(self, trade: dict) -> Path:
        ts = pacific_now()
        stamp = pacific_stamp(ts)
        from_a = trade["from_asset"]
        to_a = trade["to_asset"]
        filename = f"{stamp}-{from_a}-to-{to_a}.txt"
        path = self.receipts_dir / filename

        body = [
            "=" * 50,
            "TRADE RECEIPT",
            "=" * 50,
            f"Time:  {format_pacific(ts)}",
            "",
            trade_narrative(trade),
            "",
            format_trade_route(trade),
            f"Size:       {trade['size_pct']*100:.0f}% of {from_a} balance",
            f"Fee:        ${trade.get('fee_usd', 0):.2f}",
            f"Gain/Loss:  {pnl_label_for_trade(trade)}",
        ]

        if trade.get("type") == "multi_hop":
            body.append("")
            body.append("Legs:")
            for index, leg in enumerate(trade.get("legs", []), 1):
                body.append(
                    f"  {index}. {leg['symbol']}  "
                    f"{format_qty(leg['from_asset'], leg['from_qty'])} -> "
                    f"{format_qty(leg['to_asset'], leg['to_qty'])}  "
                    f"(fee ${leg.get('fee_usd', 0):.2f})"
                )

        body.extend(["=" * 50, ""])

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(body))
        return path
