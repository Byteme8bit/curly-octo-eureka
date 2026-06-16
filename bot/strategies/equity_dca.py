"""Scheduled dollar-cost averaging into Kraken xStocks / ETFs (USD pairs only)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from bot.equities import is_equity_asset
from bot.strategies.base import Signal, Strategy, StrategyContext, StrategyResult, TradeIntent
from config import Settings

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass
class DcaState:
    """Persisted schedule for equity DCA buys."""

    last_cycle_at: str | None = None
    cycle_index: int = 0
    last_buy: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> DcaState:
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not read DCA state (%s): %s", path, exc)
            return cls()
        if not isinstance(data, dict):
            return cls()
        last_buy = data.get("last_buy") or {}
        if not isinstance(last_buy, dict):
            last_buy = {}
        return cls(
            last_cycle_at=data.get("last_cycle_at"),
            cycle_index=int(data.get("cycle_index", 0) or 0),
            last_buy={str(k): str(v) for k, v in last_buy.items()},
        )

    def save(self, path: Path) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "last_cycle_at": self.last_cycle_at,
                        "cycle_index": self.cycle_index,
                        "last_buy": self.last_buy,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Could not write DCA state (%s): %s", path, exc)

    def hours_since_cycle(self) -> float | None:
        ts = _parse_ts(self.last_cycle_at)
        if ts is None:
            return None
        return (_utc_now() - ts).total_seconds() / 3600.0

    def hours_since_buy(self, asset: str) -> float | None:
        ts = _parse_ts(self.last_buy.get(asset))
        if ts is None:
            return None
        return (_utc_now() - ts).total_seconds() / 3600.0


class EquityDcaStrategy(Strategy):
    """
    Rotate scheduled USD -> xStock buys on EQUITY_WATCHLIST.

    DCA is accumulation, not alpha — it bypasses MIN_NET_PROFIT / edge hurdles
    (see preflight + risk gates) but still respects portfolio caps, drawdown
    halt, live allowlist, and per-trade USD limits.
    """

    name = "equity_dca"

    def __init__(self, settings: Settings):
        self.enabled = settings.dca_enabled and settings.enable_equities
        self.equity_watchlist = settings.equity_watchlist
        self.equity_assets = settings.equity_assets
        self.equity_usd_symbols = settings.equity_usd_symbols
        self.interval_hours = settings.dca_interval_hours
        self.amount_usd = settings.dca_amount_usd
        self.per_symbol_usd = settings.dca_per_symbol_usd
        self.min_usd_trade = settings.min_usd_trade
        self.max_equity_allocation_pct = settings.max_equity_allocation_pct
        self.live_enabled = settings.live_enabled
        self.live_allowed = frozenset(settings.live_allowed_assets)
        self.state_path = settings.dca_state_file
        self._state = DcaState.load(self.state_path)

    def _resolved_watchlist(self) -> tuple[str, ...]:
        """Watchlist tickers that have a USD pair on Kraken."""
        symbol_bases = {s.split("/", 1)[0] for s in self.equity_usd_symbols}
        return tuple(a for a in self.equity_watchlist if a in symbol_bases)

    def _budget_usd(self, watchlist: tuple[str, ...]) -> float:
        if self.per_symbol_usd > 0:
            return self.per_symbol_usd
        if not watchlist:
            return 0.0
        return self.amount_usd / len(watchlist)

    def _pick_symbol(self, watchlist: tuple[str, ...]) -> str | None:
        if not watchlist:
            return None
        if self.per_symbol_usd > 0:
            for asset in watchlist:
                elapsed = self._state.hours_since_buy(asset)
                if elapsed is None or elapsed >= self.interval_hours:
                    return asset
            return None
        elapsed = self._state.hours_since_cycle()
        if elapsed is not None and elapsed < self.interval_hours:
            return None
        idx = self._state.cycle_index % len(watchlist)
        return watchlist[idx]

    def _live_allowed(self, asset: str) -> bool:
        if not self.live_enabled:
            return True
        return asset in self.live_allowed

    def on_trade_executed(self, intent: TradeIntent) -> None:
        """Persist schedule after a successful DCA fill."""
        asset = intent.to_asset
        if not is_equity_asset(asset, self.equity_assets):
            return
        now = _utc_now().isoformat()
        self._state.last_buy[asset] = now
        if self.per_symbol_usd <= 0:
            watchlist = self._resolved_watchlist()
            if watchlist:
                self._state.cycle_index = (self._state.cycle_index + 1) % len(watchlist)
            self._state.last_cycle_at = now
        self._state.save(self.state_path)

    def evaluate(
        self,
        candles: dict[str, pd.DataFrame],
        prices: dict[str, float],
        holdings: dict[str, float],
        risk=None,
        markets=None,
        context: StrategyContext | None = None,
    ) -> StrategyResult:
        if not self.enabled:
            return StrategyResult(
                signals={},
                scores={},
                reasons={},
                sizes={},
                idle_reason="Equity DCA disabled (DCA_ENABLED=0 or ENABLE_EQUITIES=0)",
            )

        if risk and risk.is_paused():
            return StrategyResult(
                signals={},
                scores={},
                reasons={},
                sizes={},
                idle_reason=risk.pause_status(),
            )

        watchlist = self._resolved_watchlist()
        if not watchlist:
            return StrategyResult(
                signals={},
                scores={},
                reasons={},
                sizes={},
                idle_reason="Equity DCA — no resolved USD pairs on watchlist",
            )

        asset = self._pick_symbol(watchlist)
        if asset is None:
            return StrategyResult(
                signals={},
                scores={},
                reasons={},
                sizes={},
                idle_reason=f"Equity DCA — next buy in <= {self.interval_hours:.0f}h",
            )

        if not self._live_allowed(asset):
            return StrategyResult(
                signals={},
                scores={},
                reasons={},
                sizes={},
                blocked=[
                    f"Equity DCA — {asset} not in LIVE_ALLOWED_ASSETS (live mirror would skip)"
                ],
                idle_reason="Equity DCA — waiting for live allowlist",
            )

        budget = self._budget_usd(watchlist)
        usd_balance = holdings.get("USD", 0.0)
        if context and context.live_usd_balance is not None:
            usd_balance = max(usd_balance, context.live_usd_balance)
        if usd_balance < self.min_usd_trade:
            return StrategyResult(
                signals={},
                scores={},
                reasons={},
                sizes={},
                blocked=[f"Equity DCA — USD balance ${usd_balance:.2f} below min trade"],
                idle_reason="Equity DCA — insufficient USD",
            )
        if budget < self.min_usd_trade:
            return StrategyResult(
                signals={},
                scores={},
                reasons={},
                sizes={},
                blocked=[f"Equity DCA — budget ${budget:.2f} below MIN_USD_TRADE"],
                idle_reason="Equity DCA — budget too small",
            )

        trade_usd = min(budget, usd_balance)
        size_pct = min(1.0, trade_usd / usd_balance) if usd_balance > 0 else 0.0
        if size_pct <= 0:
            return StrategyResult(
                signals={},
                scores={},
                reasons={},
                sizes={},
                idle_reason="Equity DCA — zero size",
            )

        price = prices.get(asset, 0.0)
        alloc = 0.0
        if price > 0:
            portfolio = usd_balance + sum(
                q * prices.get(a, 0.0) for a, q in holdings.items() if a != "USD"
            )
            if portfolio > 0:
                alloc = (holdings.get(asset, 0.0) * price) / portfolio

        if alloc >= self.max_equity_allocation_pct:
            return StrategyResult(
                signals={},
                scores={},
                reasons={},
                sizes={},
                blocked=[
                    f"Equity DCA — {asset} at {alloc:.1%} (cap {self.max_equity_allocation_pct:.0%})"
                ],
                idle_reason="Equity DCA — at allocation cap",
            )

        mode = "per-symbol" if self.per_symbol_usd > 0 else "split"
        intent = TradeIntent(
            from_asset="USD",
            to_asset=asset,
            reason=(
                f"Equity DCA ({mode}) — scheduled buy ${trade_usd:.2f} of {asset}/USD "
                f"every {self.interval_hours:.0f}h"
            ),
            size_pct=size_pct,
            edge=0.0,
            gross_return_pct=0.0,
            is_accumulation=True,
            strategy_name=self.name,
        )
        return StrategyResult(
            signals={asset: Signal.BUY},
            scores={},
            reasons={asset: intent.reason},
            sizes={asset: size_pct},
            intents=[intent],
        )
