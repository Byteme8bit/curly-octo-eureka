"""Strategy C — cross-pair relative momentum (15m/1h EMA + RVOL)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pandas as pd

from bot.strategies.base import Signal, Strategy, StrategyContext, StrategyResult, TradeIntent, RotationOption
from bot.strategies.momentum_rotation import MomentumRotationStrategy
from config import Settings

if TYPE_CHECKING:
    from bot.markets import MarketRegistry
    from bot.risk import RiskManager

logger = logging.getLogger(__name__)


class CrossMomentumStrategy(Strategy):
    """
    Combines 15-minute and 1-hour EMA momentum with relative volume (RVOL)
    to rotate from stagnant holdings into breakout leaders.
    """

    name = "cross_momentum"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.usd_symbols = settings.usd_symbols
        self.symbol_assets = settings.symbol_assets
        self.asset_usd_symbols = settings.asset_usd_symbols
        self.ema_fast = settings.ema_fast
        self.ema_slow = settings.ema_slow
        self.trade_size_pct = settings.trade_size_pct
        self.dust_usd = settings.dust_usd
        self.min_net_profit_pct = settings.min_net_profit_pct
        self._rotation = MomentumRotationStrategy(settings)

    def _ema_momentum(self, df: pd.DataFrame, fast: int, slow: int) -> float:
        close = df["close"]
        if len(close) < slow:
            return 0.0
        fast_ema = close.ewm(span=fast, adjust=False).mean().iloc[-1]
        slow_ema = close.ewm(span=slow, adjust=False).mean().iloc[-1]
        if slow_ema == 0:
            return 0.0
        return float((fast_ema - slow_ema) / slow_ema)

    def _rvol(self, df: pd.DataFrame, lookback: int = 20) -> float:
        if len(df) < lookback + 1:
            return 1.0
        vol = df["volume"]
        avg = vol.iloc[-lookback - 1 : -1].mean()
        if avg <= 0:
            return 1.0
        return float(vol.iloc[-1] / avg)

    def _multi_tf_score(
        self,
        asset: str,
        context: StrategyContext | None,
        fallback_candles: dict[str, pd.DataFrame],
    ) -> float:
        symbol = self.asset_usd_symbols.get(asset)
        if not symbol:
            return 0.0

        scores: list[float] = []
        weights: list[float] = []

        if context and context.candles_by_timeframe:
            tf_weights = {"15m": 0.45, "1h": 0.55}
            for tf, weight in tf_weights.items():
                tf_candles = context.candles_by_timeframe.get(tf, {})
                df = tf_candles.get(symbol)
                if df is not None and len(df) >= self.ema_slow:
                    mom = self._ema_momentum(df, self.ema_fast, self.ema_slow)
                    rvol = self._rvol(df)
                    scores.append(mom * min(2.0, rvol))
                    weights.append(weight)
        else:
            df = fallback_candles.get(symbol)
            if df is not None:
                mom = self._ema_momentum(df, self.ema_fast, self.ema_slow)
                rvol = self._rvol(df)
                scores.append(mom * min(2.0, rvol))
                weights.append(1.0)

        if not scores:
            return 0.0
        total_w = sum(weights)
        return sum(s * w for s, w in zip(scores, weights)) / total_w

    def evaluate(
        self,
        candles: dict[str, pd.DataFrame],
        prices: dict[str, float],
        holdings: dict[str, float],
        risk: RiskManager | None = None,
        markets: MarketRegistry | None = None,
        context: StrategyContext | None = None,
    ) -> StrategyResult:
        # Delegate rotation logic to momentum_rotation, but override scores with multi-TF RVOL blend
        base = self._rotation.evaluate(
            candles, prices, holdings, risk=risk, markets=markets, context=context
        )

        enhanced_scores = {
            symbol: self._multi_tf_score(self.symbol_assets[symbol], context, candles)
            for symbol in self.usd_symbols
            if symbol in self.symbol_assets
        }
        if self.settings.equity_preference_tickers and self.settings.equity_preference_score_boost:
            pref = frozenset(self.settings.equity_preference_tickers)
            boost = self.settings.equity_preference_score_boost
            for symbol in self.usd_symbols:
                asset = self.symbol_assets.get(symbol)
                if asset and asset in pref and asset in self.settings.equity_assets:
                    enhanced_scores[symbol] = enhanced_scores.get(symbol, 0.0) + boost
        if any(v != 0 for v in enhanced_scores.values()):
            base.scores = enhanced_scores

        for intent in base.intents:
            intent.strategy_name = self.name
            if intent.gross_return_pct <= 0:
                intent.gross_return_pct = intent.edge

        for opp in base.opportunities:
            opp.category = "cross_momentum" if opp.category == "rotation" else opp.category

        if not base.intents and not base.idle_reason:
            base.idle_reason = "Cross momentum — scanning 15m/1h breakouts"

        return base
