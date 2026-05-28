"""Apply / list / revert auditor proposals against ``runtime_overrides.json``.

This file is the ONLY persistence side of the auditor that mutates engine
behavior. We deliberately do not touch ``.env`` so reverting is just a key
removal. The auditor only writes knobs from
``bot.auditor.proposer.ALLOWED_KNOBS``; anything else passed in is rejected.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from bot.auditor.proposer import ALLOWED_KNOBS, ConfigProposal

logger = logging.getLogger(__name__)


def _load(overrides_file: Path) -> dict[str, float]:
    if not overrides_file.exists():
        return {}
    try:
        raw = json.loads(overrides_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("runtime_overrides.json unreadable (%s) — treating as empty", exc)
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for knob, value in raw.items():
        if knob not in ALLOWED_KNOBS:
            continue
        try:
            out[knob] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def _save(overrides_file: Path, data: dict[str, float]) -> None:
    overrides_file.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({k: float(v) for k, v in data.items()}, indent=2, sort_keys=True)
    tmp = overrides_file.with_suffix(overrides_file.suffix + ".tmp")
    tmp.write_text(payload + "\n", encoding="utf-8")
    tmp.replace(overrides_file)


def apply_proposal(proposal: ConfigProposal, overrides_file: Path) -> None:
    """Write a single proposal's knob -> value into ``runtime_overrides.json``.

    Raises ``ValueError`` if the knob is not in ``ALLOWED_KNOBS`` — the
    service layer should already have validated, this is a defence-in-depth
    check.
    """
    if proposal.knob not in ALLOWED_KNOBS:
        raise ValueError(f"Refusing to override disallowed knob: {proposal.knob}")
    data = _load(overrides_file)
    data[proposal.knob] = float(proposal.proposed_value)
    _save(overrides_file, data)
    logger.warning(
        "Auditor override applied: %s=%s (proposal %s)",
        proposal.knob, proposal.proposed_value, proposal.id,
    )


def list_overrides(overrides_file: Path) -> dict[str, float]:
    """Return the currently active overrides (filtered to allowed knobs)."""
    return _load(overrides_file)


def revert_override(knob: str, overrides_file: Path) -> bool:
    """Remove a knob from ``runtime_overrides.json``.

    Returns True if the knob was present and removed, False otherwise.
    """
    if knob not in ALLOWED_KNOBS:
        return False
    data = _load(overrides_file)
    if knob not in data:
        return False
    del data[knob]
    if data:
        _save(overrides_file, data)
    else:
        if overrides_file.exists():
            overrides_file.unlink()
    logger.warning("Auditor override reverted: %s", knob)
    return True
