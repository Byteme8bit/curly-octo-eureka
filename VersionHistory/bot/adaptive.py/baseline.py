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


def compute_relax_factor(idle_hours: float, idle_threshold_hours: float) -> float:
    """
    After idle_threshold_hours with no trade, relax requirements gradually.
    Reaches ~50% of normal strictness after 6 hours beyond threshold.
    """
    if idle_hours < idle_threshold_hours:
        return 1.0
    extra = idle_hours - idle_threshold_hours
    return max(0.5, 1.0 - extra * 0.083)


def fee_floor_edge(fee_rate: float, hops: int, *, is_held_swap: bool = False) -> float:
    """Minimum edge that still clears per-leg taker fees with a tiny buffer."""
    buffer = 1.08 if is_held_swap else 1.05
    return fee_rate * max(1, hops) * buffer


def relaxed_threshold(base: float, floor: float, relax_factor: float) -> float:
    if relax_factor >= 1.0:
        return base
    return max(floor, base * relax_factor)
