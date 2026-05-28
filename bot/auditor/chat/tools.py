"""Read-only tool registry for Auditor chat.

Each ``Tool`` wraps a plain Python callable that returns JSON-serialisable
data. The LLM backend gets a list of these descriptors and decides which to
invoke for a given user question. The callables are deliberately:

- Read-only — no writes to disk, no trade execution paths, no Discord posts.
- Defensive — failures return ``{"error": ...}`` so the LLM can describe the
  failure to the user without crashing the chat loop.
- Schema-described — every tool ships a JSON-Schema-ish ``parameters`` dict
  that the backend converts to provider-native function declarations.

To add a new tool, write a function returning a dict / list, then register it
in ``build_tool_registry``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

logger = logging.getLogger(__name__)


# Soft caps to keep tool payloads small enough for LLM context windows.
MAX_TRADES_RETURNED = 50
MAX_ERRORS_RETURNED = 25
MAX_NEWS_RETURNED = 15


@dataclass(frozen=True)
class Tool:
    """A read-only callable exposed to the LLM with a JSON-Schema description."""

    name: str
    description: str
    parameters: dict  # JSON-Schema fragment for an "object" type
    handler: Callable[..., Any]

    def invoke(self, args: Mapping[str, Any] | None) -> Any:
        kwargs = dict(args or {})
        try:
            return self.handler(**kwargs)
        except TypeError as exc:
            logger.warning("Tool %s called with bad args %s: %s", self.name, kwargs, exc)
            return {"error": f"invalid arguments for {self.name}: {exc}"}
        except Exception as exc:  # noqa: BLE001 — never crash chat
            logger.exception("Tool %s raised", self.name)
            return {"error": f"{self.name} failed: {exc}"}


@dataclass
class ToolRegistry:
    tools: list[Tool] = field(default_factory=list)

    def names(self) -> list[str]:
        return [t.name for t in self.tools]

    def find(self, name: str) -> Tool | None:
        for t in self.tools:
            if t.name == name:
                return t
        return None

    def __iter__(self) -> Iterable[Tool]:
        return iter(self.tools)

    def __len__(self) -> int:
        return len(self.tools)


# ---------------------------------------------------------------------------
# tool implementations
# ---------------------------------------------------------------------------


def _safe_get(obj: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if obj is None:
            return default
        obj = getattr(obj, name, None) if not isinstance(obj, Mapping) else obj.get(name)
    return default if obj is None else obj


def _trade_to_payload(trade: Mapping[str, Any]) -> dict:
    """Reduce a stored trade dict to a compact LLM-friendly subset."""
    return {
        "timestamp": trade.get("timestamp") or trade.get("ts") or "",
        "strategy": trade.get("strategy") or "",
        "from_asset": trade.get("from_asset") or "",
        "to_asset": trade.get("to_asset") or "",
        "from_amount": trade.get("from_amount"),
        "to_amount": trade.get("to_amount"),
        "gain_loss": trade.get("gain_loss", 0.0),
        "fee_usd": trade.get("fee_usd", trade.get("fee", 0.0)),
        "price_usd": trade.get("price_usd"),
        "reason": trade.get("reason") or "",
    }


def make_get_portfolio_snapshot(broker, portfolio_log=None) -> Callable[[], dict]:
    def _impl() -> dict:
        balances: dict[str, float] = {}
        state = getattr(broker, "state", None)
        if state is not None:
            raw = getattr(state, "balances", {})
            if isinstance(raw, Mapping):
                balances = {k: float(v) for k, v in raw.items() if v}
        peak = float(_safe_get(broker, "risk", "peak_portfolio", default=0.0) or 0.0)
        snap = portfolio_log.load() if portfolio_log is not None else None
        summary_line = snap.summary_line() if snap and snap.summary_line() else ""
        return {
            "balances": balances,
            "peak_portfolio_usd": peak,
            "summary_line": summary_line,
        }
    return _impl


def make_get_recent_trades(broker) -> Callable[..., dict]:
    def _impl(limit: int = 20, asset: str | None = None, strategy: str | None = None) -> dict:
        limit = max(1, min(int(limit or 20), MAX_TRADES_RETURNED))
        state = getattr(broker, "state", None)
        raw_trades = getattr(state, "trades", []) if state is not None else []
        items = [t for t in raw_trades if isinstance(t, Mapping)]
        if asset:
            up = asset.upper()
            items = [
                t for t in items
                if str(t.get("from_asset", "")).upper() == up
                or str(t.get("to_asset", "")).upper() == up
            ]
        if strategy:
            sl = strategy.lower()
            items = [t for t in items if str(t.get("strategy", "")).lower() == sl]
        recent = items[-limit:][::-1]  # newest first
        return {
            "count": len(recent),
            "trades": [_trade_to_payload(t) for t in recent],
            "total_recorded": len(raw_trades),
        }
    return _impl


def make_get_strategy_performance(broker) -> Callable[..., dict]:
    def _impl() -> dict:
        state = getattr(broker, "state", None)
        trades = getattr(state, "trades", []) if state is not None else []
        per: dict[str, dict] = {}
        for t in trades:
            if not isinstance(t, Mapping):
                continue
            name = str(t.get("strategy") or "unknown")
            slot = per.setdefault(
                name,
                {"trade_count": 0, "wins": 0, "losses": 0, "total_pnl": 0.0, "total_fees": 0.0},
            )
            slot["trade_count"] += 1
            gl = float(t.get("gain_loss", 0.0) or 0.0)
            slot["total_pnl"] += gl
            slot["total_fees"] += float(t.get("fee_usd", t.get("fee", 0.0)) or 0.0)
            if gl > 0:
                slot["wins"] += 1
            elif gl < 0:
                slot["losses"] += 1
        for slot in per.values():
            total = slot["wins"] + slot["losses"]
            slot["win_rate"] = (slot["wins"] / total) if total else 0.0
        return {"by_strategy": per}
    return _impl


def make_get_active_overrides(overrides_file: Path) -> Callable[[], dict]:
    def _impl() -> dict:
        from bot.auditor.runtime_overrides import list_overrides

        return {"overrides": list_overrides(overrides_file)}
    return _impl


def make_get_pending_proposals(state_provider: Callable[[], Any]) -> Callable[[], dict]:
    def _impl() -> dict:
        state = state_provider()
        if state is None or not hasattr(state, "pending_proposals"):
            return {"proposals": []}
        out = []
        for pid, prop in state.pending_proposals.items():
            try:
                out.append(prop.to_dict())
            except Exception:  # noqa: BLE001
                out.append({"id": pid})
        return {"proposals": out}
    return _impl


def make_get_last_audit_summary(reports_dir: Path) -> Callable[..., dict]:
    def _impl(max_chars: int = 4000) -> dict:
        max_chars = max(200, min(int(max_chars or 4000), 16000))
        try:
            days = sorted(
                [p for p in reports_dir.iterdir() if p.is_dir()],
                reverse=True,
            )
        except FileNotFoundError:
            return {"path": None, "summary": "No audit reports yet."}
        for day in days:
            try:
                audits = sorted(day.glob("audit-*.md"), reverse=True)
            except OSError:
                continue
            for audit in audits:
                try:
                    text = audit.read_text(encoding="utf-8")
                except OSError as exc:
                    return {"path": str(audit), "error": str(exc)}
                if len(text) > max_chars:
                    text = text[:max_chars] + "\n…(truncated)"
                return {"path": str(audit), "summary": text}
        return {"path": None, "summary": "No audit reports yet."}
    return _impl


def make_get_watchdog_health(watchdog_state_provider: Callable[[], Any]) -> Callable[[], dict]:
    def _impl() -> dict:
        state = watchdog_state_provider() if watchdog_state_provider else None
        if state is None:
            return {"available": False, "reason": "watchdog state not available"}
        if isinstance(state, Mapping):
            return {"available": True, **{k: state[k] for k in state if not str(k).startswith("_")}}
        # Dataclass-like — convert to dict best-effort
        keys = [a for a in dir(state) if not a.startswith("_") and not callable(getattr(state, a))]
        out: dict = {"available": True}
        for k in keys:
            try:
                v = getattr(state, k)
                json.dumps(v)  # serialisability gate
                out[k] = v
            except Exception:  # noqa: BLE001
                continue
        return out
    return _impl


def make_get_recent_errors(watchdog_state_provider: Callable[[], Any]) -> Callable[..., dict]:
    def _impl(limit: int = 10, source: str | None = None) -> dict:
        limit = max(1, min(int(limit or 10), MAX_ERRORS_RETURNED))
        state = watchdog_state_provider() if watchdog_state_provider else None
        if state is None:
            return {"errors": []}
        errors = []
        for attr in ("bot_errors", "watchdog_errors", "errors"):
            val = getattr(state, attr, None) if not isinstance(state, Mapping) else state.get(attr)
            if isinstance(val, list):
                tagged_source = "bot" if attr == "bot_errors" else (
                    "watchdog" if attr == "watchdog_errors" else "mixed"
                )
                for e in val:
                    if not isinstance(e, Mapping):
                        continue
                    if source and tagged_source != source.lower():
                        continue
                    errors.append({**dict(e), "source": tagged_source})
        # Newest first by timestamp when available
        errors.sort(key=lambda e: e.get("at") or e.get("timestamp") or 0, reverse=True)
        return {"errors": errors[:limit]}
    return _impl


def make_get_recent_news(news_client_provider: Callable[[], Any]) -> Callable[..., dict]:
    def _impl(limit: int = 5, ticker: str | None = None) -> dict:
        limit = max(1, min(int(limit or 5), MAX_NEWS_RETURNED))
        client = news_client_provider() if news_client_provider else None
        if client is None:
            return {"headlines": [], "available": False}
        assets = [ticker.upper()] if ticker else []
        try:
            headlines = client.fetch_headlines(assets, limit)
        except Exception as exc:  # noqa: BLE001
            return {"headlines": [], "error": str(exc)}
        out = []
        for h in headlines:
            out.append({
                "title": getattr(h, "title", ""),
                "url": getattr(h, "url", ""),
                "source": getattr(h, "source", ""),
                "published_at": getattr(h, "published_at", ""),
                "tickers": list(getattr(h, "tickers", []) or []),
                "sentiment": getattr(h, "sentiment", "unknown"),
            })
        return {"headlines": out, "available": True}
    return _impl


def make_get_bot_settings(settings) -> Callable[..., dict]:
    """Return a curated subset of effective Settings (with overrides already applied)."""

    KEYS = (
        "min_trade_edge",
        "min_net_profit_pct",
        "trade_size_pct",
        "fee_rate",
        "idle_reeval_hours",
        "strategy_exploration_ratio",
        "min_eth_reserve",
        "max_alt_allocation_pct",
        "watch_assets",
        "usd_symbols",
        "candle_timeframe",
        "poll_interval",
        "strategy_names",
    )

    def _impl() -> dict:
        out: dict = {}
        for k in KEYS:
            v = getattr(settings, k, None)
            if v is None:
                continue
            try:
                json.dumps(v)
                out[k] = v
            except TypeError:
                out[k] = str(v)
        return out
    return _impl


def make_get_market_prices(broker) -> Callable[..., dict]:
    def _impl() -> dict:
        prices = getattr(getattr(broker, "state", None), "mark_prices", None)
        if isinstance(prices, Mapping):
            return {"prices_usd": {k: float(v) for k, v in prices.items() if v}}
        # Fallback: try a cached last-known map
        cached = getattr(broker, "last_known_prices_usd", None)
        if isinstance(cached, Mapping):
            return {"prices_usd": {k: float(v) for k, v in cached.items() if v}}
        return {"prices_usd": {}, "note": "no cached USD marks available"}
    return _impl


# ---------------------------------------------------------------------------
# factory
# ---------------------------------------------------------------------------


def build_tool_registry(
    *,
    broker,
    settings,
    portfolio_log=None,
    overrides_file: Path,
    audit_state_provider: Callable[[], Any],
    watchdog_state_provider: Callable[[], Any] | None = None,
    news_client_provider: Callable[[], Any] | None = None,
    reports_dir: Path,
) -> ToolRegistry:
    """Build the standard read-only tool registry for an AuditorService instance."""

    tools: list[Tool] = [
        Tool(
            name="get_portfolio_snapshot",
            description=(
                "Current balances per asset (numeric), the peak portfolio USD value, "
                "and a one-line summary including drawdown. Use first when the user "
                "asks 'how are we doing' or about holdings."
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            handler=make_get_portfolio_snapshot(broker, portfolio_log),
        ),
        Tool(
            name="get_recent_trades",
            description=(
                "List the most recent executed trades, newest first. Filter by asset "
                "(e.g. 'ETH') or strategy name (e.g. 'cross_momentum'). Use when the "
                "user asks about specific trades, recent activity, or why something happened."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max trades to return (1-50). Default 20."},
                    "asset": {"type": "string", "description": "Filter to trades touching this asset ticker."},
                    "strategy": {"type": "string", "description": "Filter to this strategy name."},
                },
                "required": [],
            },
            handler=make_get_recent_trades(broker),
        ),
        Tool(
            name="get_strategy_performance",
            description=(
                "Per-strategy aggregates: trade count, wins, losses, win rate, total "
                "PnL, total fees. Use when the user asks which strategy is best or "
                "wants a strategy comparison."
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            handler=make_get_strategy_performance(broker),
        ),
        Tool(
            name="get_active_overrides",
            description=(
                "Show every knob currently overridden by runtime_overrides.json (the "
                "auditor's applied proposals). Empty dict means no overrides active."
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            handler=make_get_active_overrides(overrides_file),
        ),
        Tool(
            name="get_pending_proposals",
            description=(
                "Auditor proposals waiting for `Auditor -confirm`. Each has id, knob, "
                "current_value, proposed_value, severity, rationale, expires_at."
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            handler=make_get_pending_proposals(audit_state_provider),
        ),
        Tool(
            name="get_last_audit_summary",
            description=(
                "Read the most recent audit markdown report in full. Useful when the "
                "user asks 'summarize the latest audit' or 'what did the audit say'."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "max_chars": {"type": "integer", "description": "Truncate at this many chars (default 4000, max 16000)."},
                },
                "required": [],
            },
            handler=make_get_last_audit_summary(reports_dir),
        ),
        Tool(
            name="get_watchdog_health",
            description=(
                "Current health snapshot: error counts, last heartbeat, score, paused state. "
                "Use when the user asks about watchdog status or bot health."
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            handler=make_get_watchdog_health(watchdog_state_provider or (lambda: None)),
        ),
        Tool(
            name="get_recent_errors",
            description=(
                "Recent errors recorded by the watchdog. Filter `source` to 'bot' or "
                "'watchdog' to narrow. Use when the user asks 'has anything broken' or "
                "wants to understand a specific failure."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max errors to return (1-25). Default 10."},
                    "source": {"type": "string", "description": "'bot' or 'watchdog' to filter by origin."},
                },
                "required": [],
            },
            handler=make_get_recent_errors(watchdog_state_provider or (lambda: None)),
        ),
        Tool(
            name="get_recent_news",
            description=(
                "Crypto headlines (free RSS/CoinGecko aggregator). Pass `ticker` to "
                "focus on a coin. Each headline has title, url, source, published_at, "
                "tickers, sentiment."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max headlines (1-15). Default 5."},
                    "ticker": {"type": "string", "description": "Filter/prioritise this ticker (e.g. 'ETH')."},
                },
                "required": [],
            },
            handler=make_get_recent_news(news_client_provider or (lambda: None)),
        ),
        Tool(
            name="get_bot_settings",
            description=(
                "Effective trading-engine settings AFTER runtime overrides. Use when "
                "the user asks 'what's our current edge requirement' or about config."
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            handler=make_get_bot_settings(settings),
        ),
        Tool(
            name="get_market_prices",
            description=(
                "Most recent USD mark prices the bot has on file for the watched "
                "assets. May be empty if no tick has fired yet."
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            handler=make_get_market_prices(broker),
        ),
    ]
    return ToolRegistry(tools=tools)
