"""Structured JSONL event sink for trades and pre-flight rejects.

Writes one JSON object per line to ``<log_dir>/events.jsonl``.  The file is
append-only, human-readable with ``jq``, and trivially consumable by pandas
or any log-aggregation pipeline.

Thread-safe — appends are serialised through a lock.

Event schema (common fields)
-----------------------------
- ``ts``          ISO-8601 UTC timestamp
- ``event``       ``"trade"`` | ``"preflight_reject"``

Trade-specific fields
---------------------
- ``strategy``    strategy name string
- ``from_asset``  e.g. ``"ETH"``
- ``to_asset``    e.g. ``"AAVE"``
- ``from_qty``    float
- ``to_qty``      float
- ``fee_usd``     float
- ``gain_loss``   float (realised PnL in USD at execution prices)
- ``type``        trade type string (``"usd"``, ``"cross"``, ``"multi_hop"``)
- ``hops``        int
- ``reason``      strategy reason string

Pre-flight reject fields
------------------------
- ``strategy``    strategy name
- ``from_asset``  intended from-asset
- ``to_asset``    intended to-asset
- ``gross_pct``   gross return %
- ``fee_pct``     compounded fee %
- ``slippage_pct`` per-hop slippage %
- ``net_pct``     net = gross - fees - slippage
- ``threshold``   min_net_profit_pct at time of rejection
- ``reason``      full rejection reason string
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_FILENAME = "events.jsonl"


class StructuredLogger:
    """Append JSONL event records to ``<log_dir>/events.jsonl``."""

    def __init__(self, log_dir: Path) -> None:
        self._path = log_dir / _FILENAME
        self._lock = threading.Lock()
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("StructuredLogger: could not create log dir %s: %s", log_dir, exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log_trade(self, trade: dict) -> None:
        """Emit a ``trade`` JSONL record from a filled-trade dict."""
        record: dict = {
            "ts": _utc_now(),
            "event": "trade",
            "strategy": trade.get("strategy_name") or "unknown",
            "from_asset": trade.get("from_asset", ""),
            "to_asset": trade.get("to_asset", ""),
            "from_qty": float(trade.get("from_qty", 0.0)),
            "to_qty": float(trade.get("to_qty", 0.0)),
            "fee_usd": float(trade.get("fee_usd", 0.0)),
            "gain_loss": float(trade.get("gain_loss", 0.0)),
            "type": trade.get("type", "usd"),
            "hops": int(trade.get("hops", 1)),
            "reason": (trade.get("reason") or "")[:500],
        }
        self._emit(record)

    def log_preflight_reject(
        self,
        *,
        strategy: str,
        from_asset: str,
        to_asset: str,
        gross_pct: float,
        fee_pct: float,
        slippage_pct: float,
        net_pct: float,
        threshold: float,
        reason: str,
    ) -> None:
        """Emit a ``preflight_reject`` JSONL record."""
        record: dict = {
            "ts": _utc_now(),
            "event": "preflight_reject",
            "strategy": strategy,
            "from_asset": from_asset,
            "to_asset": to_asset,
            "gross_pct": round(gross_pct, 6),
            "fee_pct": round(fee_pct, 6),
            "slippage_pct": round(slippage_pct, 6),
            "net_pct": round(net_pct, 6),
            "threshold": round(threshold, 6),
            "reason": reason[:500],
        }
        self._emit(record)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _emit(self, record: dict) -> None:
        line = json.dumps(record, separators=(",", ":"))
        try:
            with self._lock:
                with open(self._path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
        except OSError as exc:
            logger.warning("StructuredLogger: write failed: %s", exc)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
