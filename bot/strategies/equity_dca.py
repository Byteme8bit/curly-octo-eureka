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
        self.equity_preference_tickers = settings.equity_preference_tickers
        self.equity_assets = settings.equity_assets
        self.equity_usd_symbols = settings.equity_usd_symbols
        self.interval_hours = settings.dca_interval_hours
        self.amount_usd = settings.dca_amount_usd
        self.per_symbol_usd = settings.dca_per_symbol_usd
        self.min_usd_trade = settings.min_usd_trade
        self.max_equity_allocation_pct = settings.max_equity_allocation_pct
        self.max_equity_bucket_pct = settings.max_equity_bucket_pct
        self.target_equity_allocation_pct = settings.target_equity_allocation_pct
        self.equity_dca_priority = settings.equity_dca_priority
        self.equity_accumulation_min_pct = settings.equity_accumulation_min_pct
        self.equity_accumulation_phase = settings.equity_accumulation_phase
        self.live_enabled = settings.live_enabled
        self.live_allowed = frozenset(settings.live_allowed_assets)
        self.state_path = settings.dca_state_file
        self._state = DcaState.load(self.state_path)

    def _resolved_watchlist(self) -> tuple[str, ...]:
        """Watchlist tickers that have a USD pair on Kraken."""
        symbol_bases = {s.split("/", 1)[0] for s in self.equity_usd_symbols}
        return tuple(a for a in self.equity_watchlist if a in symbol_bases)

    def _preference_weight(self, asset: str) -> int:
        if not self.equity_preference_tickers:
            return 1
        return 2 if asset in frozenset(self.equity_preference_tickers) else 1

    def _weighted_watchlist(self, watchlist: tuple[str, ...]) -> list[str]:
        """Preference tickers appear twice for round-robin / budget weighting."""
        out: list[str] = []
        for asset in watchlist:
            out.extend([asset] * self._preference_weight(asset))
        return out

    def _equity_bucket_pct(
        self, holdings: dict[str, float], prices: dict[str, float]
    ) -> float:
        portfolio = holdings.get("USD", 0.0) + sum(
            q * prices.get(a, 0.0) for a, q in holdings.items() if a != "USD"
        )
        if portfolio <= 0:
            return 0.0
        equity_usd = sum(
            holdings.get(a, 0.0) * prices.get(a, 0.0) for a in self.equity_assets
        )
        return equity_usd / portfolio

    def _in_accumulation(self, holdings: dict[str, float], prices: dict[str, float]) -> bool:
        equity_pct = self._equity_bucket_pct(holdings, prices)
        if equity_pct < self.equity_accumulation_min_pct:
            return True
        if self.equity_accumulation_phase and equity_pct < self.target_equity_allocation_pct:
            return True
        return False

    def _effective_interval_hours(
        self, holdings: dict[str, float], prices: dict[str, float]
    ) -> float:
        if self.equity_dca_priority and self._in_accumulation(holdings, prices):
            return max(6.0, self.interval_hours * 0.5)
        return self.interval_hours

    def _budget_usd(self, watchlist: tuple[str, ...], asset: str) -> float:
        if self.per_symbol_usd > 0:
            weight = self._preference_weight(asset)
            return self.per_symbol_usd * weight
        if not watchlist:
            return 0.0
        total_weight = sum(self._preference_weight(a) for a in watchlist)
        if total_weight <= 0:
            return 0.0
        return self.amount_usd * self._preference_weight(asset) / total_weight

    def _pick_symbol(
        self, watchlist: tuple[str, ...], *, interval_hours: float
    ) -> str | None:
        if not watchlist:
            return None
        weighted = self._weighted_watchlist(watchlist)
        if self.per_symbol_usd > 0:
            for asset in weighted:
                elapsed = self._state.hours_since_buy(asset)
                if elapsed is None or elapsed >= interval_hours:
                    return asset
            return None
        elapsed = self._state.hours_since_cycle()
        if elapsed is not None and elapsed < interval_hours:
            return None
        idx = self._state.cycle_index % len(weighted)
        return weighted[idx]

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
            weighted = self._weighted_watchlist(watchlist)
            if weighted:
                self._state.cycle_index = (self._state.cycle_index + 1) % len(weighted)
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

        interval_hours = self._effective_interval_hours(holdings, prices)
        equity_bucket = self._equity_bucket_pct(holdings, prices)
        if equity_bucket >= self.max_equity_bucket_pct:
            return StrategyResult(
                signals={},
                scores={},
                reasons={},
                sizes={},
                blocked=[
                    f"Equity DCA — equity bucket {equity_bucket:.1%} "
                    f"at cap {self.max_equity_bucket_pct:.0%}"
                ],
                idle_reason="Equity DCA — equity bucket at target",
            )

        asset = self._pick_symbol(watchlist, interval_hours=interval_hours)
        if asset is None:
            return StrategyResult(
                signals={},
                scores={},
                reasons={},
                sizes={},
                idle_reason=f"Equity DCA — next buy in <= {interval_hours:.0f}h",
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

        budget = self._budget_usd(watchlist, asset)
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
        priority = "priority " if self.equity_dca_priority and self._in_accumulation(holdings, prices) else ""
        intent = TradeIntent(
            from_asset="USD",
            to_asset=asset,
            reason=(
                f"Equity DCA ({priority}{mode}) — scheduled buy ${trade_usd:.2f} of {asset}/USD "
                f"every {interval_hours:.0f}h (equity bucket {equity_bucket:.1%})"
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
