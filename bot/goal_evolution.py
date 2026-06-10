"""Portfolio milestone goals, strategy expansion, and crash-hold guard."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bot.local_time import format_pacific

logger = logging.getLogger(__name__)

TIER_LABELS = ("Baseline", "Growth", "Scale", "Elite")


def build_manager_from_settings(settings) -> GoalEvolutionManager:
    """Construct manager from ``config.Settings``."""
    milestones = settings.goal_milestones_usd
    if len(milestones) < 3:
        milestones = (10000.0, 100000.0, 1000000.0)

    tier_strategies = (
        settings.goal_tier0_strategies,
        settings.goal_tier1_strategies,
        settings.goal_tier2_strategies,
        settings.goal_tier3_strategies,
    )
    tiers: list[GoalTier] = [
        GoalTier(
            level=0,
            threshold_usd=0.0,
            label=TIER_LABELS[0],
            strategies=tier_strategies[0],
            unlock_summary="Core momentum rotation",
        ),
    ]
    for idx, threshold in enumerate(milestones[:3], start=1):
        exploration = None
        whale_mult = 1.0
        if idx == 2:
            exploration = settings.goal_tier2_exploration_ratio
        elif idx == 3:
            exploration = settings.goal_tier3_exploration_ratio
            whale_mult = settings.goal_tier3_whale_follow_size_mult
        tiers.append(
            GoalTier(
                level=idx,
                threshold_usd=threshold,
                label=TIER_LABELS[idx] if idx < len(TIER_LABELS) else f"Tier {idx}",
                strategies=tier_strategies[idx],
                exploration_ratio=exploration,
                whale_follow_size_mult=whale_mult,
            )
        )

    goal_cfg = GoalEvolutionConfig(
        enabled=settings.goal_evolution_enabled,
        state_file=settings.goal_state_file,
        tiers=tuple(tiers),
        base_exploration_ratio=settings.strategy_exploration_ratio,
    )
    crash_cfg = CrashGuardConfig(
        enabled=settings.crash_hold_enabled,
        drawdown_pct=settings.crash_hold_drawdown_pct,
        session_drawdown_pct=settings.crash_hold_session_drawdown_pct,
        recovery_drawdown_pct=settings.crash_hold_recovery_drawdown_pct,
        momentum_threshold=settings.crash_hold_momentum_threshold,
        momentum_asset_ratio=settings.crash_hold_momentum_asset_ratio,
        watchdog_drawdown_pct=settings.crash_hold_watchdog_drawdown_pct,
        min_hold_minutes=settings.crash_hold_min_minutes,
    )
    return GoalEvolutionManager(goal_cfg, crash_cfg)


@dataclass(frozen=True)
class GoalTier:
    """One portfolio milestone tier and its unlock profile."""

    level: int
    threshold_usd: float
    label: str
    strategies: tuple[str, ...]
    exploration_ratio: float | None = None
    whale_follow_size_mult: float = 1.0
    unlock_summary: str = ""


@dataclass(frozen=True)
class GoalEvolutionConfig:
    enabled: bool
    state_file: Path
    tiers: tuple[GoalTier, ...]
    base_exploration_ratio: float


@dataclass(frozen=True)
class CrashGuardConfig:
    enabled: bool
    drawdown_pct: float
    session_drawdown_pct: float
    recovery_drawdown_pct: float
    momentum_threshold: float
    momentum_asset_ratio: float
    watchdog_drawdown_pct: float
    min_hold_minutes: float


@dataclass
class GoalEvolutionState:
    achieved_tiers: list[int] = field(default_factory=list)
    last_announced_tier: int = -1
    crash_hold_active: bool = False
    crash_hold_since: str | None = None
    crash_hold_reason: str = ""
    crash_hold_triggers: list[str] = field(default_factory=list)
    session_start_portfolio: float = 0.0
    session_start_at: str | None = None
    last_portfolio_usd: float = 0.0
    last_tier: int = 0

    def save(self, path: Path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)

    @classmethod
    def load(cls, path: Path) -> GoalEvolutionState:
        if not path.exists():
            return cls()
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Goal evolution state unreadable (%s) — starting fresh", exc)
            return cls()
        if not isinstance(data, dict):
            return cls()
        achieved = data.get("achieved_tiers") or []
        if not isinstance(achieved, list):
            achieved = []
        triggers = data.get("crash_hold_triggers") or []
        if not isinstance(triggers, list):
            triggers = []
        return cls(
            achieved_tiers=[int(x) for x in achieved],
            last_announced_tier=int(data.get("last_announced_tier", -1)),
            crash_hold_active=bool(data.get("crash_hold_active", False)),
            crash_hold_since=data.get("crash_hold_since"),
            crash_hold_reason=str(data.get("crash_hold_reason", "")),
            crash_hold_triggers=[str(t) for t in triggers],
            session_start_portfolio=float(data.get("session_start_portfolio", 0.0)),
            session_start_at=data.get("session_start_at"),
            last_portfolio_usd=float(data.get("last_portfolio_usd", 0.0)),
            last_tier=int(data.get("last_tier", 0)),
        )


@dataclass(frozen=True)
class GoalStatus:
    enabled: bool
    tier: int
    tier_label: str
    portfolio_usd: float
    next_threshold_usd: float | None
    next_tier_label: str
    allowed_strategies: tuple[str, ...]
    exploration_ratio: float
    whale_follow_size_mult: float
    unlocked_capabilities: tuple[str, ...]
    newly_achieved: bool
    achievement_message: str


@dataclass(frozen=True)
class CrashGuardStatus:
    active: bool
    reason: str
    triggers: tuple[str, ...]
    since: str | None
    blocks_new_risk: bool
    newly_activated: bool
    newly_released: bool
    release_message: str
    activate_message: str


def tier_for_portfolio(tiers: tuple[GoalTier, ...], portfolio_usd: float) -> GoalTier:
    current = tiers[0]
    for tier in tiers:
        if portfolio_usd >= tier.threshold_usd:
            current = tier
        else:
            break
    return current


def next_tier(tiers: tuple[GoalTier, ...], current: GoalTier) -> GoalTier | None:
    for tier in tiers:
        if tier.level > current.level:
            return tier
    return None


class GoalEvolutionManager:
    """Tracks portfolio milestones and applies gradual strategy expansion."""

    def __init__(self, config: GoalEvolutionConfig, crash_config: CrashGuardConfig):
        self.config = config
        self.crash_config = crash_config
        self.state = GoalEvolutionState.load(config.state_file)

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _save(self) -> None:
        self.config.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state.save(self.config.state_file)

    def _tier_by_level(self, level: int) -> GoalTier:
        for tier in self.config.tiers:
            if tier.level == level:
                return tier
        return self.config.tiers[0]

    def effective_exploration_ratio(self, tier: GoalTier) -> float:
        if tier.exploration_ratio is not None:
            return tier.exploration_ratio
        return self.config.base_exploration_ratio

    def evaluate_goals(self, portfolio_usd: float) -> GoalStatus:
        if not self.config.enabled:
            tier = self._tier_by_level(0)
            return GoalStatus(
                enabled=False,
                tier=tier.level,
                tier_label=tier.label,
                portfolio_usd=portfolio_usd,
                next_threshold_usd=None,
                next_tier_label="",
                allowed_strategies=tier.strategies,
                exploration_ratio=self.effective_exploration_ratio(tier),
                whale_follow_size_mult=tier.whale_follow_size_mult,
                unlocked_capabilities=(),
                newly_achieved=False,
                achievement_message="",
            )

        tier = tier_for_portfolio(self.config.tiers, portfolio_usd)
        nxt = next_tier(self.config.tiers, tier)
        achieved = set(self.state.achieved_tiers)
        newly = False
        message = ""

        for t in self.config.tiers:
            if t.level <= tier.level:
                if t.level not in achieved:
                    achieved.add(t.level)
                    newly = True
                    if t.level > self.state.last_announced_tier:
                        message = self._format_achievement(t, tier)
                        self.state.last_announced_tier = t.level

        self.state.achieved_tiers = sorted(achieved)
        self.state.last_tier = tier.level
        self.state.last_portfolio_usd = portfolio_usd
        if self.state.session_start_portfolio <= 0:
            self.state.session_start_portfolio = portfolio_usd
            self.state.session_start_at = self._now().isoformat()
        self._save()

        caps = self._capabilities(tier)
        return GoalStatus(
            enabled=True,
            tier=tier.level,
            tier_label=tier.label,
            portfolio_usd=portfolio_usd,
            next_threshold_usd=nxt.threshold_usd if nxt else None,
            next_tier_label=nxt.label if nxt else "Max tier",
            allowed_strategies=tier.strategies,
            exploration_ratio=self.effective_exploration_ratio(tier),
            whale_follow_size_mult=tier.whale_follow_size_mult,
            unlocked_capabilities=caps,
            newly_achieved=newly and bool(message),
            achievement_message=message,
        )

    def _capabilities(self, tier: GoalTier) -> tuple[str, ...]:
        caps: list[str] = []
        if "stat_arb" in tier.strategies:
            caps.append("Stat-arb pairs")
        if "triangular_arbitrage" in tier.strategies:
            caps.append("Triangular arb loops")
        if tier.exploration_ratio is not None:
            caps.append(f"Exploration {tier.exploration_ratio:.0%}")
        if tier.whale_follow_size_mult > 1.0:
            caps.append(f"Whale-follow sizing ×{tier.whale_follow_size_mult:.2f}")
        if not caps:
            caps.append("Core momentum only")
        return tuple(caps)

    def _format_achievement(self, achieved: GoalTier, current: GoalTier) -> str:
        caps = ", ".join(self._capabilities(achieved)) or achieved.unlock_summary
        return (
            f"**Goal reached — {achieved.label}** (${achieved.threshold_usd:,.0f}+)\n"
            f"Portfolio ${self.state.last_portfolio_usd:,.2f}. Now unlocked: {caps}."
        )

    def filter_configured_strategies(
        self,
        configured: tuple[str, ...],
        allowed: tuple[str, ...],
    ) -> tuple[str, ...]:
        allowed_set = set(allowed)
        filtered = tuple(s for s in configured if s in allowed_set)
        if filtered:
            return filtered
        return allowed

    def evaluate_crash_guard(
        self,
        *,
        portfolio_usd: float,
        peak_drawdown_pct: float,
        asset_momentum: dict[str, float] | None = None,
        watchdog_drawdown_pct: float = 0.0,
        risk_paused: bool = False,
        trading_active: bool = True,
    ) -> CrashGuardStatus:
        cfg = self.crash_config
        if not cfg.enabled:
            return CrashGuardStatus(
                active=False,
                reason="",
                triggers=(),
                since=None,
                blocks_new_risk=False,
                newly_activated=False,
                newly_released=False,
                release_message="",
                activate_message="",
            )

        if risk_paused or not trading_active:
            return CrashGuardStatus(
                active=self.state.crash_hold_active,
                reason=self.state.crash_hold_reason,
                triggers=tuple(self.state.crash_hold_triggers),
                since=self.state.crash_hold_since,
                blocks_new_risk=False,
                newly_activated=False,
                newly_released=False,
                release_message="",
                activate_message="",
            )

        triggers: list[str] = []
        if peak_drawdown_pct >= cfg.drawdown_pct:
            triggers.append(f"peak drawdown {peak_drawdown_pct:.1%}")
        session_start = self.state.session_start_portfolio
        if session_start > 0:
            session_dd = max(0.0, (session_start - portfolio_usd) / session_start)
            if session_dd >= cfg.session_drawdown_pct:
                triggers.append(f"session drawdown {session_dd:.1%}")

        if asset_momentum:
            negatives = sum(
                1 for score in asset_momentum.values() if score <= cfg.momentum_threshold
            )
            total = len(asset_momentum)
            if total > 0 and negatives / total >= cfg.momentum_asset_ratio:
                triggers.append(
                    f"momentum crash ({negatives}/{total} assets ≤ {cfg.momentum_threshold:+.2%})"
                )

        if watchdog_drawdown_pct >= cfg.watchdog_drawdown_pct:
            triggers.append(f"watchdog drawdown {watchdog_drawdown_pct:.1%}")

        was_active = self.state.crash_hold_active
        newly_activated = False
        newly_released = False
        activate_message = ""
        release_message = ""

        if triggers and not was_active:
            self.state.crash_hold_active = True
            self.state.crash_hold_since = self._now().isoformat()
            self.state.crash_hold_reason = "; ".join(triggers)
            self.state.crash_hold_triggers = triggers
            newly_activated = True
            when = format_pacific(self._now())
            activate_message = (
                f"**CRASH HOLD** — {self.state.crash_hold_reason}\n"
                f"New risk paused at {when}. Defensive holds only until recovery."
            )
        elif was_active:
            since = self._parse(self.state.crash_hold_since)
            min_elapsed = (
                since is not None
                and (self._now() - since) >= timedelta(minutes=cfg.min_hold_minutes)
            )
            recovered_dd = peak_drawdown_pct <= cfg.recovery_drawdown_pct
            momentum_ok = not any("momentum crash" in t for t in self.state.crash_hold_triggers) or (
                asset_momentum
                and sum(1 for s in asset_momentum.values() if s <= cfg.momentum_threshold)
                / max(1, len(asset_momentum))
                < cfg.momentum_asset_ratio
            )
            if min_elapsed and recovered_dd and momentum_ok and not triggers:
                self.state.crash_hold_active = False
                self.state.crash_hold_since = None
                self.state.crash_hold_reason = ""
                self.state.crash_hold_triggers = []
                newly_released = True
                release_message = (
                    f"**Crash hold released** — drawdown {peak_drawdown_pct:.1%}, "
                    "momentum stabilized. Resuming normal trading."
                )

        self.state.last_portfolio_usd = portfolio_usd
        self._save()

        active = self.state.crash_hold_active
        return CrashGuardStatus(
            active=active,
            reason=self.state.crash_hold_reason,
            triggers=tuple(self.state.crash_hold_triggers),
            since=self.state.crash_hold_since,
            blocks_new_risk=active,
            newly_activated=newly_activated,
            newly_released=newly_released,
            release_message=release_message,
            activate_message=activate_message,
        )

    def _parse(self, value: str | None) -> datetime | None:
        if not value:
            return None
        return datetime.fromisoformat(value)

    def dashboard_view(self, portfolio_usd: float | None = None) -> dict:
        usd = portfolio_usd if portfolio_usd is not None else self.state.last_portfolio_usd
        tier = tier_for_portfolio(self.config.tiers, usd) if self.config.enabled else self.config.tiers[0]
        nxt = next_tier(self.config.tiers, tier) if self.config.enabled else None
        return {
            "enabled": self.config.enabled,
            "tier": tier.level,
            "tier_label": tier.label,
            "portfolio_usd": usd,
            "next_threshold_usd": nxt.threshold_usd if nxt else None,
            "next_tier_label": nxt.label if nxt else "Max tier",
            "allowed_strategies": list(tier.strategies),
            "exploration_ratio": self.effective_exploration_ratio(tier),
            "whale_follow_size_mult": tier.whale_follow_size_mult,
            "unlocked_capabilities": list(self._capabilities(tier)),
            "achieved_tiers": list(self.state.achieved_tiers),
            "crash_hold": {
                "active": self.state.crash_hold_active,
                "reason": self.state.crash_hold_reason,
                "since": self.state.crash_hold_since,
                "triggers": list(self.state.crash_hold_triggers),
            },
        }
