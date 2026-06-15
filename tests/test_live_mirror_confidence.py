"""Unit tests for confidence-gated live mirror decisions."""

from bot.live_mirror import should_mirror_to_live
from bot.verifier.models import Verdict


def test_should_mirror_confirm() -> None:
    ok, reason = should_mirror_to_live(
        Verdict.CONFIRM,
        {"hops": 1},
        min_confidence="confirm",
        mirror_uncertain=False,
        allow_triangular=False,
    )
    assert ok is True
    assert reason == ""


def test_should_mirror_deny() -> None:
    ok, reason = should_mirror_to_live(
        Verdict.DENY,
        {"hops": 1},
        min_confidence="always",
        mirror_uncertain=True,
        allow_triangular=True,
    )
    assert ok is False
    assert reason == "live_tag DENY"


def test_uncertain_blocked_at_confirm_level() -> None:
    ok, reason = should_mirror_to_live(
        Verdict.UNCERTAIN,
        {"hops": 1},
        min_confidence="confirm",
        mirror_uncertain=True,
        allow_triangular=True,
    )
    assert ok is False
    assert "confirm" in reason


def test_uncertain_single_leg_needs_mirror_uncertain_flag() -> None:
    ok, _ = should_mirror_to_live(
        Verdict.UNCERTAIN,
        {"hops": 1},
        min_confidence="uncertain_ok",
        mirror_uncertain=False,
        allow_triangular=False,
    )
    assert ok is False

    ok, reason = should_mirror_to_live(
        Verdict.UNCERTAIN,
        {"hops": 1},
        min_confidence="uncertain_ok",
        mirror_uncertain=True,
        allow_triangular=False,
    )
    assert ok is True
    assert reason == ""


def test_uncertain_multi_hop_needs_triangular() -> None:
    trade = {"type": "multi_hop", "hops": 3}
    ok, reason = should_mirror_to_live(
        Verdict.UNCERTAIN,
        trade,
        min_confidence="always",
        mirror_uncertain=False,
        allow_triangular=False,
    )
    assert ok is False
    assert "TRIANGULAR" in reason

    ok, _ = should_mirror_to_live(
        Verdict.UNCERTAIN,
        trade,
        min_confidence="always",
        mirror_uncertain=False,
        allow_triangular=True,
    )
    assert ok is True
