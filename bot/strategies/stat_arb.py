"""Strategy B — cross-pair statistical arbitrage (mean reversion on price ratios)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pandas as pd

from bot.strategies.base import Signal, Strategy, StrategyContext, StrategyResult, TradeIntent, RotationOption
from config import ASSET_USD_SYMBOLS, Settings

if TYPE_CHECKING:
    from bot.markets import MarketRegistry
    from bot.risk import RiskManager

logger = logging.getLogger(__name__)


class StatArbStrategy(Strategy):
    """
    Monitor ratio series between correlated assets.
    When |Z-score| > threshold, rotate from overperformer into underperformer.
    """

    name = "stat_arb"

    def __init__(self, settings: Settings):
        self.usd_symbols = settings.usd_symbols
        self.trade_size_pct = settings.trade_size_pct
        self.zscore_threshold = settings.stat_arb_zscore_threshold
        self.lookback = settings.stat_arb_lookback
        self.min_net_profit_pct = settings.min_net_profit_pct
        self.dust_usd = settings.dust_usd
        self.pairs = settings.stat_arb_pairs

    def _ratio_series(
        self, candles_a: pd.DataFrame, candles_b: pd.DataFrame
    ) -> pd.Series:
        close_a = candles_a["close"].reset_index(drop=True)
        close_b = candles_b["close"].reset_index(drop=True)
        length = min(len(close_a), len(close_b), self.lookback)
        if length < max(10, self.lookback // 2):
            return pd.Series(dtype=float)
        ratio = close_a.iloc[-length:] / close_b.iloc[-length:].replace(0, pd.NA)
        return ratio.dropna()

    def _zscore(self, series: pd.Series) -> float:
        if len(series) < 10:
            return 0.0
        mean = series.mean()
        std = series.std()
        if std == 0 or pd.isna(std):
            return 0.0
        return float((series.iloc[-1] - mean) / std)

    def evaluate(
        self,
        candles: dict[str, pd.DataFrame],
        prices: dict[str, float],
        holdings: dict[str, float],
        risk: RiskManager | None = None,
        markets: MarketRegistry | None = None,
        context: StrategyContext | None = None,
    ) -> StrategyResult:
        if risk and risk.is_paused():
            return StrategyResult(
                signals={},
                scores={},
                reasons={},
                sizes={},
                idle_reason=risk.pause_status(),
            )

        intents: list[TradeIntent] = []
        opportunities: list[RotationOption] = []
        blocked: list[str] = []
        reasons: dict[str, str] = {}

        best_signal: tuple[float, str, str, float, str] | None = None

        zscore_threshold = (
            risk.effective_stat_arb_zscore()
            if risk
            else self.zscore_threshold
        )

        for base, quote in self.pairs:
            sym_base = ASSET_USD_SYMBOLS.get(base)
            sym_quote = ASSET_USD_SYMBOLS.get(quote)
            if not sym_base or not sym_quote:
                continue
            if sym_base not in candles or sym_quote not in candles:
                continue

            ratio = self._ratio_series(candles[sym_base], candles[sym_quote])
            z = self._zscore(ratio)
            reasons[f"{base}/{quote}"] = f"z={z:+.2f}"

            if abs(z) < zscore_threshold:
                continue

            # Positive z: base outperformed quote -> rotate base into quote
            if z > 0:
                from_asset, to_asset = base, quote
                direction = "overperformer"
            else:
                from_asset, to_asset = quote, base
                direction = "underperformer reversion"

            held_qty = holdings.get(from_asset, 0.0)
            held_usd = held_qty * prices.get(from_asset, 0.0)
            if held_usd < self.dust_usd:
                blocked.append(
                    f"Stat arb {base}/{quote} z={z:+.2f} — insufficient {from_asset} ({held_usd:.0f} USD)"
                )
                continue

            gross = abs(z) * 0.001  # expected reversion edge proxy
            label = f"{base}/{quote} z={z:+.2f}"
            if best_signal is None or gross > best_signal[0]:
                best_signal = (gross, from_asset, to_asset, z, label)

        min_net = risk.effective_min_net_profit() if risk else self.min_net_profit_pct

        if best_signal:
            gross, from_asset, to_asset, z, label = best_signal
            if gross > min_net:
                intents.append(
                    TradeIntent(
                        from_asset=from_asset,
                        to_asset=to_asset,
                        reason=f"stat arb mean reversion — {label} ({z:+.2f}σ)",
                        size_pct=self.trade_size_pct,
                        edge=gross,
                        gross_return_pct=gross,
                        is_held_swap=True,
                        strategy_name=self.name,
                    )
                )
                opportunities.append(
                    RotationOption(
                        from_asset=from_asset,
                        to_asset=to_asset,
                        edge=gross,
                        required_edge=min_net,
                        category="stat_arb",
                        hops=1,
                    )
                )
            else:
                blocked.append(
                    f"Stat arb {label} edge {gross:+.4f} below min net {min_net:+.4f}"
                )

        return StrategyResult(
            signals={s: Signal.HOLD for s in self.usd_symbols},
            scores={},
            reasons=reasons,
            sizes={},
            intents=intents,
            idle_reason="Stat arb — ratios within bands" if not intents else "",
            blocked=blocked,
            opportunities=opportunities,
        )
