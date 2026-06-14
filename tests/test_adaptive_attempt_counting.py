"""Adaptive exhaustion must not fire before preflight qualifies an intent."""

from __future__ import annotations

import inspect

from bot.engine import TradingEngine


def test_record_adaptive_attempt_runs_after_preflight_qualification() -> None:
    """Regression: counting attempts when intents exist but fail constraints
    exhausted adaptive in ~3 ticks without ever reaching execution."""
    src = inspect.getsource(TradingEngine.tick)
    attempt_idx = src.index("record_adaptive_attempt")
    qualify_idx = src.index("edge_qualified = True")
    assert qualify_idx < attempt_idx, (
        "record_adaptive_attempt must run only after at least one intent "
        "passes preflight (edge_qualified)"
    )
