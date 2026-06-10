"""Goal evolution and crash-hold state for the dashboard."""

from __future__ import annotations

import json
import os
from pathlib import Path

from dashboard.config import DashboardSettings


def _parse_milestones(raw: str) -> tuple[float, ...]:
    return tuple(float(x.strip()) for x in raw.split(",") if x.strip())


def _parse_strategies(raw: str) -> tuple[str, ...]:
    return tuple(s.strip() for s in raw.split(",") if s.strip())


def _tier_labels() -> tuple[str, ...]:
    return ("Baseline", "Growth", "Scale", "Elite")


def build_goals_view(settings: DashboardSettings) -> dict:
    state_path = settings.goal_state_file
    portfolio_usd = 0.0
    if settings.paper_portfolio_file.exists():
        try:
            data = json.loads(settings.paper_portfolio_file.read_text(encoding="utf-8"))
            portfolio_usd = float(data.get("portfolio_usd", 0.0))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            portfolio_usd = 0.0

    enabled = os.getenv("GOAL_EVOLUTION_ENABLED", "1") == "1"
    milestones = _parse_milestones(os.getenv("GOAL_MILESTONES_USD", "10000,100000,1000000"))
    if len(milestones) < 3:
        milestones = (10000.0, 100000.0, 1000000.0)

    tier_strategies = (
        _parse_strategies(os.getenv("GOAL_TIER0_STRATEGIES", "cross_momentum")),
        _parse_strategies(os.getenv("GOAL_TIER1_STRATEGIES", "cross_momentum,stat_arb")),
        _parse_strategies(
            os.getenv("GOAL_TIER2_STRATEGIES", "cross_momentum,stat_arb,triangular_arbitrage")
        ),
        _parse_strategies(
            os.getenv(
                "GOAL_TIER3_STRATEGIES",
                "cross_momentum,stat_arb,triangular_arbitrage",
            )
        ),
    )
    labels = _tier_labels()
    tiers = [{"level": 0, "threshold_usd": 0.0, "label": labels[0], "strategies": list(tier_strategies[0])}]
    for idx, threshold in enumerate(milestones[:3], start=1):
        tiers.append(
            {
                "level": idx,
                "threshold_usd": threshold,
                "label": labels[idx] if idx < len(labels) else f"Tier {idx}",
                "strategies": list(tier_strategies[idx]),
            }
        )

    state = {
        "achieved_tiers": [],
        "crash_hold": {"active": False, "reason": "", "since": None, "triggers": []},
    }
    if state_path.exists():
        try:
            raw = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                state["achieved_tiers"] = raw.get("achieved_tiers") or []
                state["crash_hold"] = {
                    "active": bool(raw.get("crash_hold_active", False)),
                    "reason": str(raw.get("crash_hold_reason", "")),
                    "since": raw.get("crash_hold_since"),
                    "triggers": raw.get("crash_hold_triggers") or [],
                }
                state_portfolio = float(raw.get("last_portfolio_usd", 0.0))
                if state_portfolio > 0:
                    portfolio_usd = state_portfolio
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass

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

    return {
        "enabled": enabled,
        "portfolio_usd": portfolio_usd,
        "tier": current["level"],
        "tier_label": current["label"],
        "next_threshold_usd": next_tier["threshold_usd"] if next_tier else None,
        "next_tier_label": next_tier["label"] if next_tier else "Max tier",
        "allowed_strategies": current["strategies"],
        "achieved_tiers": state["achieved_tiers"],
        "crash_hold": state["crash_hold"],
        "milestones": tiers,
    }
