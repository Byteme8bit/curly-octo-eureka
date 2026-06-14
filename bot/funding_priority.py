"""Ranking for which held asset to spend first (ADA before ETH reserve)."""

from __future__ import annotations

_ETH_LAST_RANK = 10_000
_OTHER_RANK = 5_000


def funding_rank(asset: str, preferred: tuple[str, ...]) -> int:
    """Lower rank = prefer as trade funding source. ETH is always spent last."""
    if asset == "USD":
        return -1
    if asset == "ETH":
        return _ETH_LAST_RANK
    try:
        return preferred.index(asset)
    except ValueError:
        return _OTHER_RANK
