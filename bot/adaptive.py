"""Adaptive threshold relaxation when the bot has been idle (no trades)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AdaptiveStatus:
    active: bool
    idle_hours: float
    relax_factor: float  # 1.0 = normal; lower = looser (min ~0.5)
    fee_floor_1hop: float
    relax_attempts: int = 0
    max_relax_attempts: int = 3
    suspended: bool = False


# How fast strictness decays once past the idle threshold, per hour of extra
# idle. Tuned so the bot reaches its loosest (break-even) stance within ~15 min
# of crossing the threshold — i.e. it visibly starts probing for a trade fast
# when the market goes quiet, instead of waiting hours. (Was 0.083/hr ≈ 6h.)
_RELAX_PER_HOUR = 2.0


def compute_relax_factor(idle_hours: float, idle_threshold_hours: float) -> float:
    """
    After idle_threshold_hours with no trade, relax requirements quickly.

    Reaches the ~0.5 floor (edges loosened toward fee break-even) within about
    15 minutes past the threshold so the bot promptly attempts small probe
    trades when it has been idle, instead of sitting silent for hours.
    """
    if idle_hours < idle_threshold_hours:
        return 1.0
    extra = idle_hours - idle_threshold_hours
    return max(0.5, 1.0 - extra * _RELAX_PER_HOUR)


def fee_floor_edge(fee_rate: float, hops: int, *, is_held_swap: bool = False) -> float:
    """Minimum edge that still clears per-leg taker fees with a tiny buffer."""
    buffer = 1.08 if is_held_swap else 1.05
    return fee_rate * max(1, hops) * buffer


def relaxed_threshold(base: float, floor: float, relax_factor: float) -> float:
    if relax_factor >= 1.0:
        return base
    return max(floor, base * relax_factor)
