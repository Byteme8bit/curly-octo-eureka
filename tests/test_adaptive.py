"""Tests for adaptive (idle-probe) threshold relaxation."""

from __future__ import annotations

from bot.adaptive import compute_relax_factor, relaxed_threshold


def test_no_relaxation_before_threshold():
    assert compute_relax_factor(idle_hours=0.1, idle_threshold_hours=0.25) == 1.0


def test_relaxation_reaches_floor_within_about_15_min_past_threshold():
    # 0.25h threshold (15 min) + 0.25h extra (≈30 min total idle) → fully relaxed.
    factor = compute_relax_factor(idle_hours=0.5, idle_threshold_hours=0.25)
    assert factor == 0.5


def test_relaxation_is_partial_shortly_after_threshold():
    # ~7.5 min past a 15 min threshold should be partway, not yet at the floor.
    factor = compute_relax_factor(idle_hours=0.375, idle_threshold_hours=0.25)
    assert 0.5 < factor < 1.0


def test_relaxation_never_below_floor():
    factor = compute_relax_factor(idle_hours=10.0, idle_threshold_hours=0.25)
    assert factor == 0.5


def test_relaxed_threshold_respects_fee_floor():
    # Even fully relaxed, the threshold is clamped to the fee floor — no
    # guaranteed-losing probe trades.
    floor = 0.004
    assert relaxed_threshold(base=0.006, floor=floor, relax_factor=0.5) == floor


def test_relaxed_threshold_normal_when_not_relaxed():
    assert relaxed_threshold(base=0.006, floor=0.004, relax_factor=1.0) == 0.006
