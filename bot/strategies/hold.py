import pandas as pd

from bot.strategies.base import Signal, Strategy, StrategyResult
from config import Settings


class HoldStrategy(Strategy):
    """Never trades — useful for testing data feeds."""

    name = "hold"

    def __init__(self, settings: Settings):
        self.usd_symbols = settings.usd_symbols

    def evaluate(
        self,
        candles: dict[str, pd.DataFrame],
        prices: dict[str, float],
        holdings: dict[str, float],
        risk=None,
        markets=None,
        context=None,
    ) -> StrategyResult:
        return StrategyResult(
            signals={symbol: Signal.HOLD for symbol in self.usd_symbols},
            scores={symbol: 0.0 for symbol in self.usd_symbols},
            reasons={},
            sizes={},
            intents=[],
            idle_reason="Hold strategy — no trades",
            blocked=[],
        )
