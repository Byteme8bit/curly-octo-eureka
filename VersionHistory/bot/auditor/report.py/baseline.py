"""Markdown report + Discord summary renderers.

Pure-string output; the service layer is responsible for actually writing
the file to ``reports/YYYY-MM-DD/audit-HHMMSS.md`` and posting to Discord.
Tests assert section presence and the Discord summary length cap.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from bot.auditor.analyzer import PortfolioInsights, StrategyPerformance
from bot.auditor.forecaster import ForecastBand
from bot.auditor.news_client import NewsHeadline
from bot.auditor.proposer import ConfigProposal
from bot.local_time import format_pacific


DISCORD_MAX_LEN = 1900  # leave room for Discord's 2000 char hard limit


@dataclass
class AuditReport:
    """Single audit run's output, returned by ``AuditorService.run_audit``."""

    trigger: str
    started_at: str
    markdown_path: Path | None
    summary: str
    insights: PortfolioInsights
    forecast: list[ForecastBand]
    headlines: list[NewsHeadline]
    proposals: list[ConfigProposal] = field(default_factory=list)


def _money(v: float) -> str:
    return f"${v:,.2f}"


def _pct(v: float) -> str:
    return f"{v * 100:.2f}%"


def _format_news_tag(headline) -> str:
    """Render the leading `[tag]` for a news bullet.

    Priority:
      * `[Source, sentiment]` when both source and a meaningful sentiment exist
      * `[Source]` when we have a source (the common RSS case)
      * `[sentiment]` when only sentiment is meaningful
      * `[news]` as a last-resort fallback
    "unknown" sentiment is treated as missing — RSS feeds don't carry it and
    showing `[unknown]` is just visual noise.
    """
    source = (getattr(headline, "source", "") or "").strip()
    sentiment = (getattr(headline, "sentiment", "") or "").strip().lower()
    has_sentiment = sentiment in {"positive", "negative", "neutral"}
    if source and has_sentiment:
        return f"[{source}, {sentiment}]"
    if source:
        return f"[{source}]"
    if has_sentiment:
        return f"[{sentiment}]"
    return "[news]"


def _strategy_row(p: StrategyPerformance) -> str:
    pairs = ", ".join(p.pairs_used[:3]) + ("…" if len(p.pairs_used) > 3 else "")
    drag = f"{p.fee_drag_ratio:.2f}x" if p.fee_drag_ratio != float("inf") else "∞"
    return (
        f"| `{p.strategy}` | {p.trade_count} | {p.wins}W/{p.losses}L | "
        f"{p.win_rate:.0%} | {_money(p.avg_gain)} | {_money(p.avg_loss)} | "
        f"{_money(p.total_pnl)} | {_money(p.total_fees)} | {drag} | {pairs} |"
    )


def render_markdown_report(
    insights: PortfolioInsights,
    forecast: list[ForecastBand],
    headlines: list[NewsHeadline],
    proposals: list[ConfigProposal],
    *,
    settings,
    trigger: str = "manual",
    extra_refs: dict[str, str] | None = None,
) -> str:
    """Full markdown report. Sections match the feature spec verbatim."""

    now = format_pacific()
    lines: list[str] = []

    # 1) Audit metadata
    lines.append(f"# Auditor report — {now}")
    lines.append("")
    lines.append(f"- **Trigger:** `{trigger}`")
    lines.append(f"- **Generated:** {now}")
    lines.append(f"- **Period:** {insights.period_start or 'n/a'} → {insights.period_end or 'n/a'}")
    lines.append(f"- **Total trades:** {insights.total_trades}")
    lines.append("")

    # 2) Headline numbers
    lines.append("## Headline numbers")
    lines.append("")
    lines.append(f"- **Net PnL:** {_money(insights.net_pnl)} (gross {_money(insights.total_pnl)} − fees {_money(insights.total_fees)})")
    lines.append(f"- **Win rate:** {insights.win_rate:.1%}")
    lines.append(f"- **Max drawdown (equity-curve):** {_money(insights.drawdown_max)}")
    lines.append(f"- **Defensive / circuit-breaker trades:** {insights.recent_circuit_breaker_events}")
    lines.append("")

    # 3) Strategy attribution
    lines.append("## Strategy attribution")
    lines.append("")
    if insights.by_strategy:
        lines.append("| Strategy | Trades | W/L | Win rate | Avg gain | Avg loss | Total PnL | Fees | Fee drag | Top pairs |")
        lines.append("|---|---:|---|---:|---:|---:|---:|---:|---:|---|")
        for perf in insights.by_strategy:
            lines.append(_strategy_row(perf))
        if insights.top_pair_strategy:
            lines.append("")
            lines.append("**Top profit pair+strategy:**")
            for symbol, strat, pnl in insights.top_pair_strategy:
                lines.append(f"- `{symbol}` × `{strat}` → {_money(pnl)}")
        if insights.bottom_pair_strategy:
            lines.append("")
            lines.append("**Worst pair+strategy:**")
            for symbol, strat, pnl in insights.bottom_pair_strategy:
                lines.append(f"- `{symbol}` × `{strat}` → {_money(pnl)}")
    else:
        lines.append("_No trades on record yet._")
    lines.append("")

    # 4) Concentration & ETH reserve
    lines.append("## Concentration & ETH reserve")
    lines.append("")
    if insights.by_asset_concentration:
        for asset, share in sorted(insights.by_asset_concentration.items(), key=lambda x: -x[1]):
            lines.append(f"- `{asset}`: {_pct(share)}")
    else:
        lines.append("_No live holdings._")
    if insights.over_concentrated:
        cap = float(getattr(settings, "max_alt_allocation_pct", 0.40))
        lines.append("")
        lines.append(
            f"⚠ **Over cap** ({_pct(cap)}): "
            + ", ".join(f"`{a}`" for a in insights.over_concentrated)
        )
    eth = insights.eth_reserve_status
    ok = "✅" if eth.get("healthy") else "⚠"
    lines.append("")
    lines.append(
        f"{ok} **ETH reserve:** {eth.get('current_eth', 0.0):.4f} (min {eth.get('min_required', 0.0):.4f})"
    )
    lines.append("")

    # 5) Forecast
    lines.append("## Forecast")
    lines.append("")
    if forecast:
        lines.append("| Horizon | Method | Expected | 10th %ile | 90th %ile | Confidence |")
        lines.append("|---|---|---:|---:|---:|---:|")
        for band in forecast:
            lines.append(
                f"| {band.horizon} | {band.method} | {_money(band.expected_pnl)} | "
                f"{_money(band.lower_band)} | {_money(band.upper_band)} | "
                f"{band.confidence:.2f} |"
            )
    else:
        lines.append("_No forecast produced._")
    lines.append("")
    lines.append("_Confidence is heuristic only; bands are not investment advice._")
    lines.append("")

    # 6) News
    lines.append("## News headlines")
    lines.append("")
    if headlines:
        for h in headlines:
            ticker_str = ", ".join(h.tickers[:4]) if h.tickers else "—"
            published = h.published_at[:19] if h.published_at else ""
            lines.append(
                f"- **[{h.sentiment}]** [{h.title}]({h.url})  "
                f"_{h.source} · {published} · {ticker_str}_"
            )
    else:
        lines.append("_No headlines fetched._")
    lines.append("")

    # 7) Proposals
    lines.append("## Proposed config changes")
    lines.append("")
    if proposals:
        for p in proposals:
            lines.append(
                f"### `{p.knob}` — {p.severity}"
            )
            lines.append("")
            lines.append(f"- **ID:** `{p.id}`")
            lines.append(f"- **Current:** `{p.current_value}` → **Proposed:** `{p.proposed_value}`")
            lines.append(f"- **Rationale:** {p.rationale}")
            lines.append(f"- **Expires:** {p.expires_at}")
            lines.append(f"- **Apply:** `Auditor -confirm {p.id}` · **Revert later:** `Auditor -revert {p.knob}`")
            lines.append("")
    else:
        lines.append("_No proposals — current settings look consistent with observed data._")
    lines.append("")

    # 8) References
    lines.append("## References")
    lines.append("")
    refs = {
        "Paper portfolio file": str(getattr(settings, "paper_portfolio_file", "paper_portfolio.json")),
        "Paper state file": str(getattr(settings, "state_file", ".paper_state.json")),
        "Receipts dir": str(getattr(settings, "receipts_dir", "receipts")),
        "Log dir": str(getattr(settings, "log_dir", "logs")),
    }
    if extra_refs:
        refs.update(extra_refs)
    for label, value in refs.items():
        lines.append(f"- **{label}:** `{value}`")
    lines.append("")

    return "\n".join(lines)


def render_discord_summary(
    insights: PortfolioInsights,
    forecast: list[ForecastBand],
    headlines: list[NewsHeadline],
    proposals: list[ConfigProposal],
    *,
    markdown_path: Path | None = None,
    trigger: str = "manual",
) -> str:
    """Discord-safe summary; stays under ``DISCORD_MAX_LEN`` chars."""

    parts: list[str] = []
    parts.append(f"**Auditor report** _(trigger: `{trigger}`)_")
    parts.append(
        f"• {insights.total_trades} trades · win rate {insights.win_rate:.0%} · "
        f"net PnL {_money(insights.net_pnl)} (fees {_money(insights.total_fees)})"
    )
    eth = insights.eth_reserve_status
    eth_status = "ok" if eth.get("healthy") else "below floor"
    parts.append(
        f"• ETH reserve: {eth.get('current_eth', 0.0):.4f} ({eth_status}) · "
        f"max drawdown {_money(insights.drawdown_max)}"
    )
    if insights.over_concentrated:
        parts.append("⚠ Over cap: " + ", ".join(f"`{a}`" for a in insights.over_concentrated))

    top = insights.by_strategy[:2]
    if top:
        rendered = " · ".join(
            f"`{p.strategy}` {_money(p.total_pnl)} ({p.win_rate:.0%})"
            for p in top
        )
        parts.append(f"• Strategies: {rendered}")

    if forecast:
        rendered = " · ".join(
            f"{b.horizon}: {_money(b.expected_pnl)} [{_money(b.lower_band)}…{_money(b.upper_band)}] "
            f"({b.method.replace('_', ' ')}, conf {b.confidence:.2f})"
            for b in forecast
        )
        parts.append("**Forecast** " + rendered)

    if headlines:
        parts.append("**News:**")
        for h in headlines[:3]:
            title = h.title if len(h.title) <= 110 else h.title[:107] + "…"
            parts.append(f"  • {_format_news_tag(h)} {title}")

    if proposals:
        parts.append("**Proposals** — apply with `Auditor -confirm <id>` within TTL:")
        for p in proposals[:5]:
            parts.append(
                f"  • `{p.id}` `{p.knob}` {p.current_value} → {p.proposed_value} ({p.severity})"
            )
        parts.append("Use `Auditor -pending` to list, `Auditor -revert <knob>` to undo.")
    else:
        parts.append("_No config changes proposed._")

    if markdown_path is not None:
        parts.append(f"_Full report: `{markdown_path}`_")

    text = "\n".join(parts)
    if len(text) <= DISCORD_MAX_LEN:
        return text
    truncated = text[: DISCORD_MAX_LEN - 1].rstrip()
    return truncated + "…"
