"""Markdown report + Discord summary renderers.

Pure-string output; the service layer is responsible for actually writing
the file to ``reports/YYYY-MM-DD/audit-HHMMSS.md`` and posting to Discord.
Tests assert section presence and the Discord summary length cap.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from bot.auditor.analyzer import PortfolioInsights, StrategyPerformance
from bot.auditor.context import AuditGoalView, LiveAuditSnapshot, format_goal_summary_line, format_goal_summary_markdown
from bot.auditor.forecaster import ForecastBand
from bot.auditor.news_client import NewsHeadline
from bot.auditor.proposer import ConfigProposal, knobs_with_conflicts
from bot.local_time import format_pacific


DISCORD_MAX_LEN = 1900  # leave room for Discord's 2000 char hard limit
DISCORD_ATTACHMENT_MAX_BYTES = 8 * 1024 * 1024  # ~8 MB Discord attachment cap


def prepare_report_attachment(path: Path) -> tuple[bytes, str, str | None]:
    """Read an audit markdown file for Discord upload as plain text.

    Returns ``(payload_bytes, filename, truncate_note)``. ``truncate_note`` is
    set when the file exceeds ``DISCORD_ATTACHMENT_MAX_BYTES``.
    """
    text = path.read_text(encoding="utf-8")
    filename = f"{path.stem}.txt"
    encoded = text.encode("utf-8")
    if len(encoded) <= DISCORD_ATTACHMENT_MAX_BYTES:
        return encoded, filename, None
    truncated = encoded[:DISCORD_ATTACHMENT_MAX_BYTES]
    while truncated and (truncated[-1] & 0xC0) == 0x80:
        truncated = truncated[:-1]
    note = f"Report attachment truncated to 8MB — full file on disk: `{path}`"
    return truncated, f"{path.stem}-truncated.txt", note


def _format_confidence(confidence: float) -> str:
    pct = int(round(confidence * 100))
    return f"confidence: {pct}% = statistical confidence in this extrapolation"


def _format_method_label(method: str) -> str:
    labels = {
        "bootstrap": (
            "**Bootstrap** — resamples past trade outcomes at the observed trade rate "
            "to estimate likely PnL (10th–90th percentile bands)."
        ),
        "trade_rate_extrapolation": (
            "**Trade-rate extrapolation** — multiplies average net PnL per trade by "
            "the expected number of trades in the horizon."
        ),
        "insufficient_data": (
            "**Insufficient data** — fewer than 10 trades; no reliable forecast yet."
        ),
    }
    return labels.get(method, f"**{method.replace('_', ' ')}**")


def _forecast_explainer(forecast: list[ForecastBand], *, paper_only: bool = True) -> str:
    if not forecast:
        return ""
    scope = "paper simulation pace" if paper_only else "recent trade pace"
    methods = {b.method for b in forecast if b.method != "insufficient_data"}
    method_bits: list[str] = []
    if "bootstrap" in methods:
        method_bits.append(
            "Bootstrap resamples your historical trade wins/losses to simulate "
            "what might happen if that pace continues."
        )
    if "trade_rate_extrapolation" in methods:
        method_bits.append(
            "Trade-rate extrapolation projects average net PnL per trade forward "
            "over the horizon."
        )
    method_line = " ".join(method_bits)
    low = any(b.confidence < 0.3 for b in forecast if b.horizon in ("7d", "30d"))
    base = (
        f"_If **{scope}** continues, the table below shows projected net PnL by horizon. "
        "Each **confidence** percentage is how strongly the sample supports that extrapolation "
        "(not a profit guarantee)._"
    )
    if method_line:
        base = f"{base} {method_line}"
    if low:
        return (
            f"{base} "
            "7d/30d figures are **directional only** — low confidence, not targets."
        )
    return (
        f"{base} Confidence naturally drops as the horizon lengthens."
    )


def news_strategy_impact(headline: NewsHeadline) -> str:
    """Rule-based note on how TradeBot might react — honest heuristics, not LLM."""
    title = (headline.title or "").lower()
    tickers = {t.upper() for t in headline.tickers}

    crash_words = (
        "crash", "plunge", "collapse", "liquidat", "selloff", "bear market",
        "dump", "hack", "exploit", "outflow", "bankrupt",
    )
    reg_words = (
        "sec ", "regulat", "regulation", "ban ", "banned", "lawsuit", "fine ",
        "enforcement", "compliance", "subpoena",
    )
    defi_words = (
        "defi", "upgrade", "hard fork", "layer 2", " l2 ", "staking", "etf",
        "mainnet", "airdrop", "protocol launch",
    )

    if any(w in title for w in crash_words):
        return "Strategy note: defensive posture — crash_hold / circuit-breaker rules may tighten entries."
    if headline.sentiment == "negative" and (tickers & {"BTC", "ETH"} or "bitcoin" in title or "ethereum" in title):
        return "Strategy note: risk-off context — may favor defensive holds over new entries."
    if any(w in title for w in reg_words):
        return "Strategy note: no strategy change — regulation headline is context only."
    if any(w in title for w in defi_words):
        return "Strategy note: alt/momentum exposure may rise if price action confirms."
    if headline.sentiment == "positive" and tickers:
        return "Strategy note: bullish context — existing momentum strategies may lean in; no auto config change."
    return "Strategy note: no strategy change — context only."


def format_proposal_discord_block(
    proposals: list[ConfigProposal],
    *,
    pending_count: int | None = None,
) -> list[str]:
    """Discord lines for the proposals section, including overload warnings."""
    lines: list[str] = []
    count = pending_count if pending_count is not None else len(proposals)
    conflicts = knobs_with_conflicts(proposals)

    if count > 3:
        conflict_note = ""
        if conflicts:
            conflict_note = f"; conflicting knobs: {', '.join(f'`{k}`' for k in conflicts)}"
        lines.append(
            f"⚠ **{count} proposals pending** — review before confirming{conflict_note}. "
            "Only one change per knob; use `Auditor -pending` (alias `-list`)."
        )

    if proposals:
        lines.append("**Proposals** — apply with `Auditor -confirm <id>` or `Auditor -confirm all`:")
        for p in proposals[:5]:
            lines.append(
                f"  • `{p.id}` `{p.knob}` {p.current_value} → {p.proposed_value} ({p.severity})"
            )
        if conflicts:
            lines.append(
                "  _Pick ONE per knob — batch confirm refuses duplicate knobs._"
            )
        lines.append(
            "`Auditor -pending` / `-list` · `Auditor -confirm id1,id2` · `Auditor -revert <knob>`"
        )
    else:
        lines.append("_No config changes proposed._")
    return lines


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


def _headline_block(
    title: str,
    insights: PortfolioInsights,
    *,
    trade_label: str | None = None,
    drawdown_label: str = "Max drawdown (equity-curve)",
    subtitle: str | None = None,
) -> list[str]:
    lines = [f"### {title}", ""]
    if subtitle:
        lines.append(f"_{subtitle}_")
        lines.append("")
    if trade_label:
        lines.append(f"- **Trades:** {trade_label}")
    lines.append(
        f"- **Net PnL:** {_money(insights.net_pnl)} "
        f"(gross {_money(insights.total_pnl)} − fees {_money(insights.total_fees)})"
    )
    lines.append(f"- **Win rate:** {insights.win_rate:.1%}")
    lines.append(f"- **{drawdown_label}:** {_money(insights.drawdown_max)}")
    lines.append(f"- **Defensive / circuit-breaker trades:** {insights.recent_circuit_breaker_events}")
    lines.append("")
    return lines


def _live_headline_block(snapshot: LiveAuditSnapshot, live_insights: PortfolioInsights | None) -> list[str]:
    lines = ["### Live Kraken spot (real wallet)", ""]
    lines.append(
        "_Your actual Kraken spot balances — not the paper simulation._"
    )
    lines.append("")
    lines.append(f"- **Portfolio value:** {_money(snapshot.portfolio_usd)}")
    if snapshot.baseline_portfolio_usd > 0:
        lines.append(
            f"- **Session PnL (wallet MTM):** {_money(snapshot.session_pnl)} "
            f"(current portfolio vs session baseline {_money(snapshot.baseline_portfolio_usd)})"
        )
    lines.append(f"- **Live trades completed:** {snapshot.live_trades_completed}")
    if live_insights and live_insights.total_trades > 0:
        lines.append(
            f"- **Net PnL (live fills only):** {_money(live_insights.net_pnl)} "
            f"(gross {_money(live_insights.total_pnl)} − fees {_money(live_insights.total_fees)})"
        )
        lines.append(f"- **Live trade win rate:** {live_insights.win_rate:.1%}")
        lines.append(
            f"- **Live max drawdown (trade equity-curve):** {_money(live_insights.drawdown_max)}"
        )
    else:
        lines.append("- **Net PnL (live fills only):** _No live fills recorded yet._")
    lines.append("")
    lines.append(
        "_Session PnL tracks wallet value (holdings + prices); live fill PnL sums executed "
        "trade receipts only — they differ when prices move between fills._"
    )
    lines.append("")
    lines.append(
        "_Kraken Trade Prop evaluation accounts are separate products and are **not** "
        "included here — see `docs/kraken-prop.md`._"
    )
    lines.append("")
    return lines


def _strategy_row(p: StrategyPerformance) -> str:
    pairs = ", ".join(p.pairs_used[:3]) + ("…" if len(p.pairs_used) > 3 else "")
    drag = f"{p.fee_drag_ratio:.2f}x" if p.fee_drag_ratio != float("inf") else "∞"
    return (
        f"| `{p.strategy}` | {p.trade_count} | {p.wins}W/{p.losses}L | "
        f"{p.win_rate:.0%} | {_money(p.avg_gain)} | {_money(p.avg_loss)} | "
        f"{_money(p.total_pnl)} | {_money(p.total_fees)} | {drag} | {pairs} |"
    )


def _strategy_gross_total(insights: PortfolioInsights) -> float:
    return sum(p.total_pnl for p in insights.by_strategy)


def render_markdown_report(
    insights: PortfolioInsights,
    forecast: list[ForecastBand],
    headlines: list[NewsHeadline],
    proposals: list[ConfigProposal],
    *,
    settings,
    trigger: str = "manual",
    extra_refs: dict[str, str] | None = None,
    live_snapshot: LiveAuditSnapshot | None = None,
    live_insights: PortfolioInsights | None = None,
    goal_view: AuditGoalView | None = None,
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
    live_mode = bool(getattr(settings, "live_enabled", False))
    if live_mode:
        live_count = (
            live_snapshot.live_trades_completed
            if live_snapshot is not None
            else (live_insights.total_trades if live_insights else 0)
        )
        lines.append(f"- **Paper trades (sim):** {insights.total_trades}")
        lines.append(f"- **Live trades (Kraken):** {live_count}")
    else:
        lines.append(f"- **Total trades:** {insights.total_trades}")
    lines.append("")

    # 2) Headline numbers
    lines.append("## Headline numbers")
    lines.append("")
    if live_mode:
        if live_snapshot is not None:
            lines.extend(_live_headline_block(live_snapshot, live_insights))
        else:
            lines.append("### Live Kraken spot (real wallet)")
            lines.append("")
            lines.append("_Live state unavailable — check `.live_state.json` and Kraken API keys._")
            lines.append("")
        lines.extend(
            _headline_block(
                "Paper simulation only — not your Kraken balance",
                insights,
                trade_label=str(insights.total_trades),
                drawdown_label="Paper max drawdown (sim equity-curve)",
                subtitle="From `.paper_state.json` — separate book from live Kraken spot.",
            )
        )
    else:
        lines.extend(_headline_block("Paper PnL (simulation)", insights))

    goal_md = format_goal_summary_markdown(goal_view)
    if goal_md:
        lines.extend(goal_md)

    # 3) Strategy attribution
    scope = "Paper strategy attribution (simulation — gross PnL)" if live_mode else "Strategy attribution"
    lines.append(f"## {scope}")
    lines.append("")
    if insights.by_strategy:
        lines.append(
            "_Per-strategy **Gross PnL** sums to paper gross "
            f"({_money(_strategy_gross_total(insights))}), not paper net "
            f"({_money(insights.net_pnl)}). Routes may overlap; do not add rows to get net._"
        )
        lines.append("")
        lines.append("| Strategy | Trades | W/L | Win rate | Avg gain | Avg loss | Gross PnL | Fees | Fee drag | Top pairs |")
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
    if live_mode:
        lines.append("_Holdings below are from the **paper simulation** portfolio._")
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
    forecast_title = (
        "Paper simulation forecast — not a live prediction"
        if live_mode
        else "Forecast"
    )
    lines.append(f"## {forecast_title}")
    lines.append("")
    if live_mode:
        lines.append(
            "_Extrapolates **paper** trade history only — not Kraken fills or wallet MTM._"
        )
        lines.append("")
    explainer = _forecast_explainer(forecast, paper_only=True)
    if explainer:
        lines.append(explainer)
        lines.append("")
    if forecast:
        methods_used = {b.method for b in forecast}
        for method in sorted(methods_used):
            lines.append(_format_method_label(method))
        lines.append("")
        lines.append("| Horizon | Method | Expected | 10th %ile | 90th %ile | Confidence |")
        lines.append("|---|---|---:|---:|---:|---|")
        for band in forecast:
            lines.append(
                f"| {band.horizon} | {band.method} | {_money(band.expected_pnl)} | "
                f"{_money(band.lower_band)} | {_money(band.upper_band)} | "
                f"{_format_confidence(band.confidence)} |"
            )
    else:
        lines.append("_No forecast produced._")
    lines.append("")
    lines.append("_Bands are extrapolations, not investment advice or profit targets._")
    lines.append("")

    # 6) News
    lines.append("## News headlines")
    lines.append("")
    if headlines:
        for h in headlines:
            ticker_str = ", ".join(h.tickers[:4]) if h.tickers else "—"
            published = h.published_at[:19] if h.published_at else ""
            link = f"[{h.title}]({h.url})" if h.url else h.title
            lines.append(
                f"- **[{h.sentiment}]** {link}  "
                f"_{h.source} · {published} · {ticker_str}_"
            )
            lines.append(f"  - {news_strategy_impact(h)}")
    else:
        lines.append("_No headlines fetched._")
    lines.append("")

    # 7) Proposals
    lines.append("## Proposed config changes")
    lines.append("")
    if proposals:
        conflicts = knobs_with_conflicts(proposals)
        if len(proposals) > 3:
            conflict_note = ""
            if conflicts:
                conflict_note = f" Conflicting knobs: {', '.join(f'`{k}`' for k in conflicts)}."
            lines.append(
                f"> **{len(proposals)} proposals** — review before confirming.{conflict_note} "
                "Use `Auditor -pending` (alias `-list`); batch apply: `Auditor -confirm all` or "
                "`Auditor -confirm id1,id2`. Only one change per knob."
            )
            lines.append("")
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
    if live_mode:
        refs["Live state file"] = str(getattr(settings, "live_state_file", ".live_state.json"))
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
    live_snapshot: LiveAuditSnapshot | None = None,
    live_insights: PortfolioInsights | None = None,
    goal_view: AuditGoalView | None = None,
    live_enabled: bool = False,
) -> str:
    """Discord-safe summary; stays under ``DISCORD_MAX_LEN`` chars."""

    parts: list[str] = []
    parts.append(f"**Auditor report** _(trigger: `{trigger}`)_")
    if live_enabled:
        if live_snapshot is not None:
            live_line = (
                f"• **Live Kraken spot:** portfolio {_money(live_snapshot.portfolio_usd)} · "
                f"{live_snapshot.live_trades_completed} live trades"
            )
            if live_insights and live_insights.total_trades > 0:
                live_line += f" · fill net PnL {_money(live_insights.net_pnl)}"
                live_line += f" · live DD {_money(live_insights.drawdown_max)}"
            if live_snapshot.baseline_portfolio_usd > 0:
                live_line += f" · session MTM {_money(live_snapshot.session_pnl)}"
            parts.append(live_line)
        parts.append(
            f"• **Paper** (sim only — not Kraken): {insights.total_trades} trades · "
            f"win {insights.win_rate:.0%} · net PnL {_money(insights.net_pnl)} · "
            f"paper DD {_money(insights.drawdown_max)}"
        )
        goal_line = format_goal_summary_line(goal_view)
        if goal_line:
            parts.append(f"• {goal_line}")
    else:
        parts.append(
            f"• {insights.total_trades} trades · win rate {insights.win_rate:.0%} · "
            f"net PnL {_money(insights.net_pnl)} (fees {_money(insights.total_fees)}) · "
            f"max drawdown {_money(insights.drawdown_max)}"
        )
    eth = insights.eth_reserve_status
    eth_status = "ok" if eth.get("healthy") else "below floor"
    parts.append(
        f"• ETH reserve (paper sim): {eth.get('current_eth', 0.0):.4f} ({eth_status})"
    )
    if insights.over_concentrated:
        parts.append("⚠ Over cap (paper): " + ", ".join(f"`{a}`" for a in insights.over_concentrated))

    top = insights.by_strategy[:2]
    if top:
        rendered = " · ".join(
            f"`{p.strategy}` gross {_money(p.total_pnl)} ({p.win_rate:.0%})"
            for p in top
        )
        label = "Paper strategies (gross, non-additive)" if live_enabled else "Strategies"
        parts.append(f"• {label}: {rendered}")

    if forecast:
        prefix = (
            "**Paper simulation forecast — not live** "
            if live_enabled
            else "**Forecast** "
        )
        rendered = " · ".join(
            f"{b.horizon}: {_money(b.expected_pnl)} [{_money(b.lower_band)}…{_money(b.upper_band)}] "
            f"({b.method.replace('_', ' ')}, {_format_confidence(b.confidence)})"
            for b in forecast
        )
        parts.append(prefix + rendered)
        methods_used = {b.method for b in forecast if b.method != "insufficient_data"}
        if "bootstrap" in methods_used:
            parts.append(
                "_Bootstrap: resamples past trade outcomes at your observed trade rate._"
            )
        note = _forecast_explainer(forecast, paper_only=True)
        if note:
            parts.append(note)

    if headlines:
        parts.append("**News:**")
        for h in headlines[:3]:
            title = h.title if len(h.title) <= 90 else h.title[:87] + "…"
            if h.url:
                line = f"  • {_format_news_tag(h)} [{title}]({h.url})"
            else:
                line = f"  • {_format_news_tag(h)} {title}"
            parts.append(line)
            impact = news_strategy_impact(h)
            if len(impact) <= 120:
                parts.append(f"    _{impact}_")

    parts.extend(format_proposal_discord_block(proposals))

    if markdown_path is not None:
        parts.append(f"_Full report attached + on disk: `{markdown_path}`_")

    text = "\n".join(parts)
    if len(text) <= DISCORD_MAX_LEN:
        return text
    truncated = text[: DISCORD_MAX_LEN - 1].rstrip()
    return truncated + "…"
