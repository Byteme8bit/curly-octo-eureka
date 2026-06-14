"""Live/paper audit context — portfolio sources for reports when LIVE is armed."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from bot.goal_evolution import TIER_UNLOCK_SUMMARIES, compute_primary_goal


@dataclass(frozen=True)
class LiveAuditSnapshot:
    """Kraken spot wallet snapshot for auditor live sections."""

    portfolio_usd: float
    baseline_portfolio_usd: float
    session_pnl: float
    trades: list[dict]
    holdings: dict[str, float]
    live_trades_completed: int


@dataclass(frozen=True)
class AuditGoalView:
    enabled: bool
    portfolio_usd: float
    portfolio_source: str
    primary_goal: dict


def _as_path(value) -> Path:
    return value if isinstance(value, Path) else Path(str(value))


def _read_json(path) -> dict | None:
    path = _as_path(path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _load_usd_prices(settings, portfolio_log=None) -> dict[str, float]:
    prices: dict[str, float] = {"USD": 1.0}
    if portfolio_log is not None:
        try:
            snap = portfolio_log.load()
            for asset, row in snap.holdings.items():
                px = float(row.get("usd_price", 0.0))
                if px > 0:
                    prices[str(asset)] = px
            if len(prices) > 1:
                return prices
        except Exception:  # noqa: BLE001
            pass
    paper = _read_json(getattr(settings, "paper_portfolio_file", Path("paper_portfolio.json")))
    if paper:
        for asset, row in (paper.get("holdings") or {}).items():
            if isinstance(row, dict):
                px = float(row.get("usd_price", 0.0))
                if px > 0:
                    prices[str(asset)] = px
    return prices


def _portfolio_usd(balances: dict[str, float], usd_prices: dict[str, float]) -> float:
    total = 0.0
    skip = frozenset({"KFEE", "BABY", "BCH"})
    for asset, qty in balances.items():
        if qty <= 0 or asset in skip:
            continue
        if asset == "USD":
            total += qty
        else:
            total += qty * usd_prices.get(asset, 0.0)
    return total


def _live_trades_only(trades: list) -> list[dict]:
    return [t for t in trades if isinstance(t, dict) and t.get("live")]


def load_live_audit_snapshot(settings, *, live_broker=None, portfolio_log=None) -> LiveAuditSnapshot | None:
    """Load Kraken spot wallet metrics for auditor reports."""
    if not getattr(settings, "live_enabled", False):
        return None

    trades: list[dict] = []
    holdings: dict[str, float] = {}
    baseline = 0.0
    live_count = 0

    if live_broker is not None:
        try:
            trades = list(live_broker.state.trades)
            holdings = dict(live_broker.state.balances)
            baseline = float(live_broker.risk.baseline_portfolio or 0.0)
            live_count = int(live_broker.risk.live_trades_completed or 0)
        except AttributeError:
            pass
    else:
        state = _read_json(getattr(settings, "live_state_file", Path(".live_state.json")))
        if not state:
            return None
        raw_bal = state.get("balances") or {}
        if isinstance(raw_bal, dict):
            holdings = {str(k): float(v) for k, v in raw_bal.items()}
        raw_trades = state.get("trades") or []
        if isinstance(raw_trades, list):
            trades = [t for t in raw_trades if isinstance(t, dict)]
        risk = state.get("risk") or {}
        if isinstance(risk, dict):
            baseline = float(risk.get("baseline_portfolio", 0.0))
            live_count = int(risk.get("live_trades_completed", 0))

    if not holdings and not trades:
        return None

    usd_prices = _load_usd_prices(settings, portfolio_log)
    portfolio_usd = _portfolio_usd(holdings, usd_prices)
    session_pnl = portfolio_usd - baseline if baseline > 0 else 0.0

    return LiveAuditSnapshot(
        portfolio_usd=portfolio_usd,
        baseline_portfolio_usd=baseline,
        session_pnl=session_pnl,
        trades=_live_trades_only(trades),
        holdings=holdings,
        live_trades_completed=live_count,
    )


def _load_paper_portfolio_usd(settings, portfolio_log=None) -> float:
    if portfolio_log is not None:
        try:
            snap = portfolio_log.load()
            if snap.portfolio_usd > 0:
                return float(snap.portfolio_usd)
        except Exception:  # noqa: BLE001
            pass
    paper = _read_json(getattr(settings, "paper_portfolio_file", Path("paper_portfolio.json")))
    if paper:
        try:
            return float(paper.get("portfolio_usd", 0.0))
        except (TypeError, ValueError):
            pass
    return 0.0


def _parse_milestones(raw: str) -> tuple[float, ...]:
    return tuple(float(x.strip()) for x in raw.split(",") if x.strip())


def _tier_labels() -> tuple[str, ...]:
    return ("Baseline", "Growth", "Scale", "Elite")


def build_audit_goal_view(
    settings,
    *,
    live_snapshot: LiveAuditSnapshot | None = None,
    portfolio_log=None,
) -> AuditGoalView | None:
    """Primary milestone progress for auditor summaries (live wallet when armed)."""
    if not getattr(settings, "goal_evolution_enabled", True):
        return None

    paper_usd = _load_paper_portfolio_usd(settings, portfolio_log)
    live_usd = live_snapshot.portfolio_usd if live_snapshot else 0.0

    if getattr(settings, "live_enabled", False):
        portfolio_usd = live_usd if live_usd > 0 else paper_usd
        portfolio_source = "live" if live_usd > 0 else "paper"
    else:
        portfolio_usd = paper_usd
        portfolio_source = "paper"

    if portfolio_usd <= 0:
        return None

    milestones = _parse_milestones(os.getenv("GOAL_MILESTONES_USD", "10000,100000,1000000"))
    if len(milestones) < 3:
        milestones = (10000.0, 100000.0, 1000000.0)
    labels = _tier_labels()
    tiers = [{"level": 0, "threshold_usd": 0.0, "label": labels[0]}]
    for idx, threshold in enumerate(milestones[:3], start=1):
        tiers.append({
            "level": idx,
            "threshold_usd": threshold,
            "label": labels[idx] if idx < len(labels) else f"Tier {idx}",
            "unlock_summary": TIER_UNLOCK_SUMMARIES.get(idx, ""),
        })

    current = tiers[0]
    for tier in tiers:
        if portfolio_usd >= tier["threshold_usd"]:
            current = tier
        else:
            break
    next_tier = None
    for tier in tiers:
        if tier["level"] > current["level"]:
            next_tier = tier
            break

    primary = compute_primary_goal(
        portfolio_usd=portfolio_usd,
        next_threshold_usd=next_tier["threshold_usd"] if next_tier else None,
        next_tier_level=next_tier["level"] if next_tier else None,
        next_tier_label=next_tier["label"] if next_tier else "Max tier",
        unlock_summary=(next_tier or {}).get("unlock_summary", ""),
    )

    return AuditGoalView(
        enabled=True,
        portfolio_usd=portfolio_usd,
        portfolio_source=portfolio_source,
        primary_goal=primary,
    )


def format_goal_summary_line(goal: AuditGoalView | None) -> str:
    if goal is None or not goal.enabled:
        return ""
    pg = goal.primary_goal
    if not pg or pg.get("achieved"):
        return ""
    target = pg.get("target_usd")
    remaining = float(pg.get("remaining_usd", 0.0))
    if not target:
        return ""
    source = "live Kraken spot" if goal.portfolio_source == "live" else "paper"
    progress = float(pg.get("progress_pct", 0.0))
    headline = pg.get("headline", "Goal")
    return (
        f"Next milestone: **{headline}** — "
        f"${goal.portfolio_usd:,.2f} ({source}) / ${target:,.0f} "
        f"({progress:.1f}%) · need ${remaining:,.0f} more"
    )


def format_goal_summary_markdown(goal: AuditGoalView | None) -> list[str]:
    line = format_goal_summary_line(goal)
    if not line:
        return []
    return ["## Portfolio goals", "", f"- {line}", ""]
