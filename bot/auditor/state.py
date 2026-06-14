"""Auditor state persistence — pending proposals + last run timestamps.

State is stored as JSON at the path configured via ``AuditorConfig.state_file``
(default ``.auditor_state.json`` at project root). All datetime arithmetic
uses timezone-aware values; the file always stores Pacific timestamps that
round-trip through ``bot.local_time``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from bot.auditor.proposer import ConfigProposal
from bot.local_time import PACIFIC, format_pacific, pacific_now, to_pacific

logger = logging.getLogger(__name__)


def _parse_pacific(value: str | None) -> datetime | None:
    """Best-effort parse of a Pacific timestamp like ``2026-05-27 14:05:30 PDT``.

    The trailing tz abbreviation (PDT/PST) is dropped — we re-attach the
    Pacific zone explicitly because Python's strptime cannot round-trip
    ``%Z`` reliably across platforms.
    """
    if not value:
        return None
    raw = value.strip()
    parts = raw.rsplit(" ", 1)
    body = parts[0] if len(parts) == 2 else raw
    try:
        naive = datetime.strptime(body, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return naive.replace(tzinfo=PACIFIC)


@dataclass
class AuditorState:
    pending_proposals: dict[str, ConfigProposal] = field(default_factory=dict)
    last_scheduled_run_at: str | None = None
    last_event_run_at: str | None = None
    last_trade_count_at_event: int = 0
    last_pnl_at_event: float = 0.0
    # Sleep-window auto-apply audit trail
    last_auto_apply_at: str | None = None
    last_auto_apply_proposal_id: str | None = None
    last_auto_apply_knob: str | None = None
    last_auto_apply_value: float | None = None
    last_auto_apply_night_key: str | None = None  # "YYYY-MM-DD" of window start
    auto_applies_this_night: int = 0

    # ----------------------- proposal lifecycle --------------------------

    def add_proposal(self, proposal: ConfigProposal, *, replace_same_knob: bool = False) -> None:
        if replace_same_knob:
            for pid, existing in list(self.pending_proposals.items()):
                if existing.knob == proposal.knob and pid != proposal.id:
                    self.pending_proposals.pop(pid, None)
        self.pending_proposals[proposal.id] = proposal

    def consume_proposal(self, proposal_id: str) -> ConfigProposal | None:
        """Pop a proposal by id. Returns None when missing or already expired."""
        proposal = self.pending_proposals.pop(proposal_id, None)
        if proposal is None:
            return None
        return proposal

    def get_proposal(self, proposal_id: str) -> ConfigProposal | None:
        return self.pending_proposals.get(proposal_id)

    def is_expired(self, proposal: ConfigProposal, now: datetime | None = None) -> bool:
        expiry = _parse_pacific(proposal.expires_at)
        if expiry is None:
            return False
        ref = to_pacific(now) if now else pacific_now()
        return ref > expiry

    def prune_expired(self, now: datetime | None = None) -> int:
        ref = to_pacific(now) if now else pacific_now()
        expired = [
            pid for pid, p in self.pending_proposals.items()
            if self.is_expired(p, ref)
        ]
        for pid in expired:
            self.pending_proposals.pop(pid, None)
        return len(expired)

    # ------------------------- run-time markers --------------------------

    def mark_scheduled_run(self) -> None:
        self.last_scheduled_run_at = format_pacific()

    def mark_event_run(self, *, trade_count: int, pnl: float) -> None:
        self.last_event_run_at = format_pacific()
        self.last_trade_count_at_event = int(trade_count)
        self.last_pnl_at_event = float(pnl)

    def mark_auto_apply(
        self,
        *,
        proposal_id: str,
        knob: str,
        value: float,
        night_key: str,
    ) -> None:
        """Record that a sleep-window auto-apply just fired.

        ``night_key`` is the YYYY-MM-DD of the night when the window opened.
        Two consecutive auto-applies on the same night key share the counter
        (so we can enforce ``autoapply_max_per_night``).
        """
        self.last_auto_apply_at = format_pacific()
        self.last_auto_apply_proposal_id = proposal_id
        self.last_auto_apply_knob = knob
        self.last_auto_apply_value = float(value)
        if self.last_auto_apply_night_key == night_key:
            self.auto_applies_this_night += 1
        else:
            self.last_auto_apply_night_key = night_key
            self.auto_applies_this_night = 1

    # --------------------------- persistence -----------------------------

    def to_dict(self) -> dict:
        return {
            "pending_proposals": {pid: p.to_dict() for pid, p in self.pending_proposals.items()},
            "last_scheduled_run_at": self.last_scheduled_run_at,
            "last_event_run_at": self.last_event_run_at,
            "last_trade_count_at_event": self.last_trade_count_at_event,
            "last_pnl_at_event": self.last_pnl_at_event,
            "last_auto_apply_at": self.last_auto_apply_at,
            "last_auto_apply_proposal_id": self.last_auto_apply_proposal_id,
            "last_auto_apply_knob": self.last_auto_apply_knob,
            "last_auto_apply_value": self.last_auto_apply_value,
            "last_auto_apply_night_key": self.last_auto_apply_night_key,
            "auto_applies_this_night": self.auto_applies_this_night,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "AuditorState":
        if not isinstance(data, dict):
            return cls()
        proposals_raw = data.get("pending_proposals") or {}
        proposals: dict[str, ConfigProposal] = {}
        if isinstance(proposals_raw, dict):
            for pid, raw in proposals_raw.items():
                if not isinstance(raw, dict):
                    continue
                try:
                    proposals[str(pid)] = ConfigProposal.from_dict(raw)
                except (KeyError, TypeError, ValueError) as exc:
                    logger.warning("Skipping malformed auditor proposal %s: %s", pid, exc)
        last_value = data.get("last_auto_apply_value")
        try:
            last_value_f = float(last_value) if last_value is not None else None
        except (TypeError, ValueError):
            last_value_f = None
        return cls(
            pending_proposals=proposals,
            last_scheduled_run_at=data.get("last_scheduled_run_at"),
            last_event_run_at=data.get("last_event_run_at"),
            last_trade_count_at_event=int(data.get("last_trade_count_at_event", 0) or 0),
            last_pnl_at_event=float(data.get("last_pnl_at_event", 0.0) or 0.0),
            last_auto_apply_at=data.get("last_auto_apply_at"),
            last_auto_apply_proposal_id=data.get("last_auto_apply_proposal_id"),
            last_auto_apply_knob=data.get("last_auto_apply_knob"),
            last_auto_apply_value=last_value_f,
            last_auto_apply_night_key=data.get("last_auto_apply_night_key"),
            auto_applies_this_night=int(data.get("auto_applies_this_night", 0) or 0),
        )

    @classmethod
    def load(cls, path: Path) -> "AuditorState":
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Auditor state unreadable (%s) — starting fresh", exc)
            return cls()
        state = cls.from_dict(data)
        # Defense in depth: a restart should not inherit proposals that are
        # already past their TTL. Without this, the chat tool / status command
        # surface stale proposals between restarts until the next prune cycle.
        # We also persist the cleaned state immediately so the on-disk file
        # matches what is in memory — otherwise an interrupted bot would keep
        # the stale entries forever.
        pruned = state.prune_expired()
        if pruned:
            logger.warning(
                "Auditor state load: dropped %d expired proposal(s) from %s",
                pruned, path,
            )
            try:
                state.save(path)
            except OSError as exc:
                logger.warning("Could not persist pruned auditor state: %s", exc)
        return state

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(path)
