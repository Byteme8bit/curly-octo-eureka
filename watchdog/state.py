"""Persistent dedup and file offsets for the watchdog."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

# Wall-clock timestamps are seconds since epoch (~1.7e9 in 2026).
# Anything below this threshold is a stale monotonic value from an older
# build that should be discarded on load.
WALL_CLOCK_MIN = 1_000_000_000.0


def _clean_walltimes(values: list[float], *, max_age_sec: float = 86400.0) -> list[float]:
    now = time.time()
    cutoff = now - max_age_sec
    return [
        ts for ts in values
        if ts >= WALL_CLOCK_MIN and ts >= cutoff and ts <= now + 60
    ]


def _clean_wallmap(
    mapping: dict[str, float], *, max_age_sec: float = 86400.0
) -> dict[str, float]:
    now = time.time()
    cutoff = now - max_age_sec
    return {
        k: v for k, v in mapping.items()
        if v >= WALL_CLOCK_MIN and v >= cutoff and v <= now + 60
    }


def _clean_recent_errors(
    records: list[dict], *, max_age_sec: float = 86400.0
) -> list[dict]:
    """Drop ``recent_errors`` records whose ``at`` timestamp is older than
    ``max_age_sec``.

    The ``at`` field comes from the log parser and has the form
    ``"YYYY-MM-DD HH:MM:SS TZAbbr"`` (e.g. ``"2026-05-31 08:02:59 PDT"``).
    Records with an unparseable timestamp are kept defensively.
    """
    cutoff = time.time() - max_age_sec
    out: list[dict] = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        at = rec.get("at", "")
        keep = True
        if at:
            parts = str(at).rsplit(" ", 1)
            body = parts[0] if len(parts) == 2 else at
            try:
                naive = datetime.strptime(body, "%Y-%m-%d %H:%M:%S")
                ts = naive.timestamp()
                keep = ts >= cutoff
            except (ValueError, TypeError):
                pass  # unparseable timestamp — keep the record
        if keep:
            out.append(rec)
    return out


@dataclass
class WatchdogState:
    file_offsets: dict[str, int] = field(default_factory=dict)
    seen_receipts: list[str] = field(default_factory=list)
    last_pnl_band: int = 0
    last_drawdown_warn: float = 0.0
    seen_error_keys: dict[str, float] = field(default_factory=dict)
    stale_alert_sent: bool = False
    last_log_activity: float = 0.0
    last_portfolio: float = 0.0
    last_baseline: float = 0.0
    reevaluation_alerted: bool = False
    seen_diagnostics: list[str] = field(default_factory=list)
    # Bot errors only (kept name for backward compat with old state files)
    error_timestamps: list[float] = field(default_factory=list)
    watchdog_error_timestamps: list[float] = field(default_factory=list)
    trades_session: int = 0
    watchdog_pause_count: int = 0
    last_watchdog_pause_at: str | None = None
    session_started_at: str | None = None
    running: bool = False
    last_heartbeat_at: float = 0.0
    error_pin_windows: dict[str, list[float]] = field(default_factory=dict)
    recent_errors: list[dict] = field(default_factory=list)

    def save(self, path: Path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)

    @classmethod
    def load(cls, path: Path) -> "WatchdogState":
        if not path.exists():
            return cls()
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            raw_error_pin = data.get("error_pin_windows", {}) or {}
            error_pin_windows = {
                k: _clean_walltimes([float(t) for t in v])
                for k, v in raw_error_pin.items()
            }
            error_pin_windows = {k: v for k, v in error_pin_windows.items() if v}
            last_heartbeat = float(data.get("last_heartbeat_at", 0.0))
            if last_heartbeat < WALL_CLOCK_MIN:
                last_heartbeat = 0.0
            last_log_activity = float(data.get("last_log_activity", 0.0))
            if last_log_activity < WALL_CLOCK_MIN:
                last_log_activity = 0.0
            return cls(
                file_offsets={k: int(v) for k, v in data.get("file_offsets", {}).items()},
                seen_receipts=list(data.get("seen_receipts", [])),
                last_pnl_band=int(data.get("last_pnl_band", 0)),
                last_drawdown_warn=float(data.get("last_drawdown_warn", 0.0)),
                seen_error_keys=_clean_wallmap(
                    {k: float(v) for k, v in data.get("seen_error_keys", {}).items()}
                ),
                stale_alert_sent=bool(data.get("stale_alert_sent", False)),
                last_log_activity=last_log_activity,
                last_portfolio=float(data.get("last_portfolio", 0.0)),
                last_baseline=float(data.get("last_baseline", 0.0)),
                reevaluation_alerted=bool(data.get("reevaluation_alerted", False)),
                seen_diagnostics=list(data.get("seen_diagnostics", [])),
                error_timestamps=_clean_walltimes(
                    [float(t) for t in data.get("error_timestamps", [])]
                ),
                watchdog_error_timestamps=_clean_walltimes(
                    [float(t) for t in data.get("watchdog_error_timestamps", [])]
                ),
                trades_session=int(data.get("trades_session", 0)),
                watchdog_pause_count=int(data.get("watchdog_pause_count", 0)),
                last_watchdog_pause_at=data.get("last_watchdog_pause_at"),
                session_started_at=data.get("session_started_at"),
                running=bool(data.get("running", False)),
                last_heartbeat_at=last_heartbeat,
                recent_errors=_clean_recent_errors(
                    list(data.get("recent_errors", []))
                ),
                error_pin_windows=error_pin_windows,
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return cls()

    def should_alert_error(self, key: str, cooldown_sec: float) -> bool:
        now = time.time()
        last = self.seen_error_keys.get(key, 0.0)
        if now - last < cooldown_sec:
            return False
        self.seen_error_keys[key] = now
        return True

    def mark_receipt_seen(self, name: str, max_retain: int = 500) -> bool:
        if name in self.seen_receipts:
            return False
        self.seen_receipts.append(name)
        if len(self.seen_receipts) > max_retain:
            self.seen_receipts = self.seen_receipts[-max_retain:]
        return True

    def mark_diagnostic_seen(self, name: str) -> bool:
        if name in self.seen_diagnostics:
            return False
        self.seen_diagnostics.append(name)
        return True

    def record_error(self, *, source: str = "bot", max_retain: int = 200) -> None:
        """Record a non-deduped error timestamp.

        source="bot"       -> trade bot errors (penalize health, can auto-pause)
        source="watchdog"  -> watchdog self-errors (informational, lighter penalty)
        """
        bucket = (
            self.watchdog_error_timestamps if source == "watchdog"
            else self.error_timestamps
        )
        bucket.append(time.time())
        if len(bucket) > max_retain:
            del bucket[: len(bucket) - max_retain]

    def prune_errors(self, max_age_sec: float = 86400) -> None:
        cutoff = time.time() - max_age_sec
        self.error_timestamps = [ts for ts in self.error_timestamps if ts >= cutoff]
        self.watchdog_error_timestamps = [
            ts for ts in self.watchdog_error_timestamps if ts >= cutoff
        ]

    def record_trade(self) -> None:
        self.trades_session += 1

    def record_watchdog_pause(self) -> None:
        self.watchdog_pause_count += 1

    def reset_session(self) -> None:
        """Full reset — called by ``TradeBot -reset``. Clears every scoring
        signal so the score returns to 100/100 with a clean slate.

        Keeps ``file_offsets`` / ``seen_receipts`` so the watchdog doesn't
        re-process historical log lines and re-alert on them.
        """
        self.last_pnl_band = 0
        self.last_drawdown_warn = 0.0
        self.seen_error_keys.clear()
        self.stale_alert_sent = False
        self.reevaluation_alerted = False
        self.error_timestamps.clear()
        self.watchdog_error_timestamps.clear()
        self.trades_session = 0
        self.watchdog_pause_count = 0
        self.last_watchdog_pause_at = None
        self.last_heartbeat_at = 0.0
        self.recent_errors.clear()
        self.error_pin_windows.clear()

    def reset_process_session_counters(self) -> None:
        """Reset counters whose name implies per-process scope.

        Called from ``begin_session()`` on every bot startup so the
        meaning of ``trades_session`` (and friends) matches their name:
        "since this bot process started", not "since the last paper reset".

        Deliberately does NOT touch:
          - ``error_timestamps`` / ``watchdog_error_timestamps`` — preserved
            across restarts so a crash-loop bot still scores low (you want
            to see it).
          - ``seen_error_keys`` / ``stale_alert_sent`` — dedup state; reset
            would cause re-alerts on historical errors.
          - ``last_pnl_band`` / ``last_drawdown_warn`` — alert tracking.
          - file offsets / receipts — log replay protection.
        """
        self.trades_session = 0
        self.watchdog_pause_count = 0
        self.last_watchdog_pause_at = None

    def append_error(self, record: dict, max_retain: int = 30) -> None:
        self.recent_errors.append(record)
        if len(self.recent_errors) > max_retain:
            self.recent_errors = self.recent_errors[-max_retain:]

    def track_error_for_pin(self, key: str, *, window_sec: float, threshold: int) -> bool:
        """Return True when the same error occurs more than threshold times in window."""
        now = time.time()
        times = self.error_pin_windows.setdefault(key, [])
        times.append(now)
        cutoff = now - window_sec
        recent = [ts for ts in times if ts >= cutoff]
        self.error_pin_windows[key] = recent
        return len(recent) > threshold

    def read_new_bytes(self, path: Path) -> bytes:
        key = str(path.resolve())
        offset = self.file_offsets.get(key, 0)
        if not path.exists():
            return b""
        size = path.stat().st_size
        if size < offset:
            offset = 0
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read()
        self.file_offsets[key] = offset + len(data)
        return data
