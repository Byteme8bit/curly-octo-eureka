"""Confidence-gated live mirroring for LIVE_MIRROR_PAPER mode."""

from __future__ import annotations

import logging
from pathlib import Path

from bot.verifier.live_tag import is_multi_hop_trade
from bot.verifier.models import Verdict

logger = logging.getLogger(__name__)

_VALID_MIN_CONFIDENCE = frozenset({"confirm", "uncertain_ok", "always"})


def parse_live_mirror_min_confidence(raw: str) -> str:
    val = (raw or "confirm").strip().lower()
    if val not in _VALID_MIN_CONFIDENCE:
        raise ValueError(
            f"LIVE_MIRROR_MIN_CONFIDENCE must be one of {sorted(_VALID_MIN_CONFIDENCE)}; got {raw!r}"
        )
    return val


def should_mirror_to_live(
    verdict: Verdict,
    trade: dict,
    *,
    min_confidence: str,
    mirror_uncertain: bool,
    allow_triangular: bool,
) -> tuple[bool, str]:
    """Return (mirror_allowed, skip_reason)."""
    if verdict == Verdict.DENY:
        return False, "live_tag DENY"

    if verdict == Verdict.CONFIRM:
        return True, ""

    # UNCERTAIN
    if min_confidence == "confirm":
        return False, "UNCERTAIN below LIVE_MIRROR_MIN_CONFIDENCE=confirm"

    if min_confidence == "uncertain_ok" and not mirror_uncertain:
        return False, "UNCERTAIN with LIVE_MIRROR_UNCERTAIN=0"

    if is_multi_hop_trade(trade) and not allow_triangular:
        return False, "UNCERTAIN multi-hop requires LIVE_ALLOW_TRIANGULAR"

    return True, ""


def is_critical_deny(verify_tag: str) -> bool:
    """DENY reasons worth a Discord alert (pair/price failures)."""
    lower = verify_tag.lower()
    if "not on kraken" in lower or "not on exchange" in lower:
        return True
    if "kraken" in lower and "off)" in lower:
        return True
    return False


def format_live_mirror_skip_line(trade: dict, reason: str, *, verify_tag: str = "") -> str:
    from bot.local_time import format_pacific

    ts = format_pacific()
    route = f"{trade.get('from_asset', '?')}->{trade.get('to_asset', '?')}"
    symbol = trade.get("symbol", "")
    tag = f" [{verify_tag}]" if verify_tag else ""
    return f"{ts} {route} {symbol}{tag} — {reason}"


def append_live_mirror_skip(
    trade: dict,
    reason: str,
    path: Path,
    *,
    verify_tag: str = "",
) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = format_live_mirror_skip_line(trade, reason, verify_tag=verify_tag)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as exc:
        logger.warning("Could not write live mirror skip log (%s): %s", path, exc)
