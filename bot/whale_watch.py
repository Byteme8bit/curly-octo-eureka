"""Kraken whale-move watcher — large public trades and volume spikes (alert-only)."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from bot.data import KrakenData
from bot.local_time import format_pacific

logger = logging.getLogger(__name__)

EVENT_RETENTION_HOURS = 168  # 7 days
MAX_SEEN_IDS_PER_PAIR = 200


@dataclass(frozen=True)
class WhaleEvent:
    id: str
    time: str
    asset: str
    pair: str
    direction: str
    usd_size: float
    source: str
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> WhaleEvent:
        return cls(
            id=str(raw.get("id", "")),
            time=str(raw.get("time", "")),
            asset=str(raw.get("asset", "")),
            pair=str(raw.get("pair", "")),
            direction=str(raw.get("direction", "")),
            usd_size=float(raw.get("usd_size", 0.0)),
            source=str(raw.get("source", "")),
            detail=str(raw.get("detail", "")),
        )


@dataclass
class WhaleWatchState:
    last_check_at: str | None = None
    seen_trade_ids: dict[str, list[str]] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)

    def save(self, path: Path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)

    @classmethod
    def load(cls, path: Path) -> WhaleWatchState:
        if not path.exists():
            return cls()
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Whale watch state unreadable (%s) — starting fresh", exc)
            return cls()
        if not isinstance(data, dict):
            return cls()
        seen = data.get("seen_trade_ids") or {}
        if not isinstance(seen, dict):
            seen = {}
        events = data.get("events") or []
        if not isinstance(events, list):
            events = []
        return cls(
            last_check_at=data.get("last_check_at"),
            seen_trade_ids={
                str(k): [str(x) for x in v][-MAX_SEEN_IDS_PER_PAIR:]
                for k, v in seen.items()
                if isinstance(v, list)
            },
            events=[e for e in events if isinstance(e, dict)],
        )


def _parse_event_time(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        if raw.endswith((" PDT", " PST")):
            body = raw.rsplit(" ", 1)[0]
            dt = datetime.strptime(body, "%Y-%m-%d %H:%M:%S")
            return dt.replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def prune_events(events: list[dict], *, max_events: int, max_age_hours: float) -> list[dict]:
    cutoff = time.time() - max_age_hours * 3600
    kept: list[dict] = []
    for raw in events:
        ts = _parse_event_time(str(raw.get("time", "")))
        if ts is not None and ts.timestamp() < cutoff:
            continue
        kept.append(raw)
    return kept[-max_events:]


def trade_usd_size(trade: dict) -> float:
    cost = trade.get("cost")
    if cost is not None:
        try:
            return abs(float(cost))
        except (TypeError, ValueError):
            pass
    try:
        price = float(trade.get("price", 0.0))
        amount = float(trade.get("amount", 0.0))
        return abs(price * amount)
    except (TypeError, ValueError):
        return 0.0


def detect_large_trades(
    trades: list[dict],
    *,
    pair: str,
    asset: str,
    min_usd: float,
    seen_ids: set[str],
) -> list[WhaleEvent]:
    events: list[WhaleEvent] = []
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        trade_id = str(trade.get("id", ""))
        if not trade_id or trade_id in seen_ids:
            continue
        usd = trade_usd_size(trade)
        if usd < min_usd:
            continue
        side = str(trade.get("side", "unknown")).lower()
        ts_ms = trade.get("timestamp")
        if ts_ms is not None:
            dt = datetime.fromtimestamp(float(ts_ms) / 1000.0, tz=timezone.utc)
            when = format_pacific(dt)
        else:
            when = format_pacific()
        events.append(
            WhaleEvent(
                id=f"trade:{pair}:{trade_id}",
                time=when,
                asset=asset,
                pair=pair,
                direction=side,
                usd_size=usd,
                source="kraken_trade",
                detail=f"Kraken public trade {side} {trade.get('amount')} @ {trade.get('price')}",
            )
        )
    return events


def detect_volume_spike(
    candles,
    *,
    pair: str,
    asset: str,
    min_usd: float,
    spike_ratio: float,
    lookback: int = 12,
) -> WhaleEvent | None:
    if candles is None or len(candles) < lookback + 1:
        return None
    prior = candles.iloc[-(lookback + 1):-1]
    latest = candles.iloc[-1]
    avg_vol = float(prior["volume"].mean())
    if avg_vol <= 0:
        return None
    latest_vol = float(latest["volume"])
    ratio = latest_vol / avg_vol
    if ratio < spike_ratio:
        return None
    close = float(latest["close"])
    usd = latest_vol * close
    if usd < min_usd:
        return None
    ts = latest.get("timestamp")
    if ts is not None and hasattr(ts, "to_pydatetime"):
        when = format_pacific(ts.to_pydatetime())
    else:
        when = format_pacific()
    candle_id = f"vol:{pair}:{when}:{usd:.0f}"
    return WhaleEvent(
        id=candle_id,
        time=when,
        asset=asset,
        pair=pair,
        direction="spike",
        usd_size=usd,
        source="volume_spike",
        detail=f"{ratio:.1f}x avg volume ({lookback} candles), ~${usd:,.0f} notional",
    )


def format_whale_alert(event: WhaleEvent) -> str:
    label = event.source.replace("_", " ")
    if event.direction == "spike":
        body = f"**Whale alert** — {event.pair} volume spike ~**${event.usd_size:,.0f}** ({label})"
    else:
        body = (
            f"**Whale alert** — {event.pair} **{event.direction}** "
            f"**${event.usd_size:,.0f}** ({label})"
        )
    if event.detail:
        body = f"{body}\n{event.detail}"
    return body


def format_whale_log_line(event: WhaleEvent) -> str:
    """Single-line whale event for logs/whale_watch.log (not Discord)."""
    detail = f" | {event.detail}" if event.detail else ""
    return (
        f"{event.time} {event.pair} {event.direction} "
        f"${event.usd_size:,.0f} source={event.source}{detail}"
    )


def append_whale_event_log(event: WhaleEvent, path: Path) -> None:
    """Append one whale detection to the quiet file log."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = format_whale_log_line(event)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as exc:
        logger.warning("Could not write whale watch log (%s): %s", path, exc)


def events_last_24h(events: list[dict], *, now: float | None = None) -> int:
    anchor = now if now is not None else time.time()
    cutoff = anchor - 86400
    count = 0
    for raw in events:
        ts = _parse_event_time(str(raw.get("time", "")))
        if ts is not None and ts.timestamp() >= cutoff:
            count += 1
    return count


class WhaleWatcher:
    """Poll Kraken for large trades and candle volume spikes; persist for dashboard."""

    def __init__(
        self,
        *,
        enabled: bool,
        assets: tuple[str, ...],
        min_usd: float,
        poll_seconds: int,
        volume_spike_ratio: float,
        max_events: int,
        state_file: Path,
        data: KrakenData,
        fetch_trades: Callable[[str, int], list[dict]] | None = None,
        fetch_candles: Callable[[str], object] | None = None,
    ):
        self.enabled = enabled
        self.assets = assets
        self.min_usd = min_usd
        self.poll_seconds = max(15, poll_seconds)
        self.volume_spike_ratio = max(1.5, volume_spike_ratio)
        self.max_events = max(10, max_events)
        self.state_file = state_file
        self.data = data
        self._fetch_trades = fetch_trades or (lambda symbol, limit: data.fetch_trades(symbol, limit))
        self._fetch_candles = fetch_candles or data.fetch_candles
        self.state = WhaleWatchState.load(state_file)
        self._last_poll_monotonic = 0.0
        self._known_event_ids = {str(e.get("id")) for e in self.state.events if e.get("id")}

    def maybe_poll(self) -> list[WhaleEvent]:
        if not self.enabled:
            return []
        now = time.monotonic()
        if self._last_poll_monotonic and now - self._last_poll_monotonic < self.poll_seconds:
            return []
        self._last_poll_monotonic = now
        try:
            new_events = self._poll_once()
        except Exception:
            logger.exception("Whale watch poll failed")
            new_events = []
        self.state.last_check_at = format_pacific()
        self.state.events = prune_events(
            self.state.events + [e.to_dict() for e in new_events],
            max_events=self.max_events,
            max_age_hours=EVENT_RETENTION_HOURS,
        )
        self.state.save(self.state_file)
        return new_events

    def _poll_once(self) -> list[WhaleEvent]:
        discovered: list[WhaleEvent] = []
        for asset in self.assets:
            pair = f"{asset}/USD"
            seen = set(self.state.seen_trade_ids.get(pair, []))
            trades = self._fetch_trades(pair, 60)
            trade_events = detect_large_trades(
                trades,
                pair=pair,
                asset=asset,
                min_usd=self.min_usd,
                seen_ids=seen,
            )
            for trade in trades:
                tid = str(trade.get("id", ""))
                if tid:
                    seen.add(tid)
            self.state.seen_trade_ids[pair] = list(seen)[-MAX_SEEN_IDS_PER_PAIR:]
            for event in trade_events:
                if event.id not in self._known_event_ids:
                    discovered.append(event)
                    self._known_event_ids.add(event.id)
            try:
                candles = self._fetch_candles(pair)
                spike = detect_volume_spike(
                    candles,
                    pair=pair,
                    asset=asset,
                    min_usd=self.min_usd,
                    spike_ratio=self.volume_spike_ratio,
                )
            except Exception:
                logger.debug("Volume spike check failed for %s", pair, exc_info=True)
                spike = None
            if spike and spike.id not in self._known_event_ids:
                discovered.append(spike)
                self._known_event_ids.add(spike.id)
        return discovered

    def annotate_event(self, event_id: str, *, follow_status: str, follow_reason: str) -> None:
        """Persist whale-follow outcome on a stored event for dashboard badges."""
        updated = False
        for raw in self.state.events:
            if str(raw.get("id")) != event_id:
                continue
            raw["follow_status"] = follow_status
            raw["follow_reason"] = follow_reason
            updated = True
            break
        if updated:
            self.state.save(self.state_file)
