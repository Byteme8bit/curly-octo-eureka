"""News + market-flow context consulted before offensive trades.

Whale-follow and scheduled DCA bypass these gates by design: whales *are* the
flow signal; DCA is accumulation, not alpha-seeking.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence

from bot.auditor.news_client import NewsClient, NewsHeadline, parse_rss_feed_env

logger = logging.getLogger(__name__)

_CRASH_WORDS = (
    "crash",
    "plunge",
    "collapse",
    "liquidat",
    "selloff",
    "bear market",
    "dump",
    "hack",
    "exploit",
    "outflow",
    "bankrupt",
)

_CORE_NEWS_ASSETS = frozenset({"BTC", "ETH"})


@dataclass(frozen=True)
class MarketFlowSnapshot:
    regime: str  # risk_off | neutral | risk_on
    negative_ratio: float
    momentum_by_asset: dict[str, float]


@dataclass(frozen=True)
class TradeContextGate:
    allowed: bool
    reason: str = ""


def compute_market_flow(
    candles: dict,
    symbol_assets: dict[str, str],
    *,
    momentum_threshold: float,
    risk_off_ratio: float,
) -> MarketFlowSnapshot:
    """Classify short-term momentum across watched USD pairs."""
    scores: dict[str, float] = {}
    for symbol, df in candles.items():
        if df is None or len(df) < 2:
            continue
        asset = symbol_assets.get(symbol)
        if not asset:
            continue
        prev = float(df["close"].iloc[-2])
        last = float(df["close"].iloc[-1])
        if prev > 0:
            scores[asset] = (last - prev) / prev

    if not scores:
        return MarketFlowSnapshot("neutral", 0.0, scores)

    negative = sum(1 for s in scores.values() if s <= momentum_threshold)
    positive = sum(1 for s in scores.values() if s >= abs(momentum_threshold))
    total = len(scores)
    neg_ratio = negative / total
    pos_ratio = positive / total

    if neg_ratio >= risk_off_ratio:
        regime = "risk_off"
    elif pos_ratio >= risk_off_ratio:
        regime = "risk_on"
    else:
        regime = "neutral"
    return MarketFlowSnapshot(regime, neg_ratio, scores)


def _headline_is_severe(headline: NewsHeadline) -> bool:
    title = (headline.title or "").lower()
    if any(w in title for w in _CRASH_WORDS):
        return True
    if headline.sentiment == "negative" and (
        _CORE_NEWS_ASSETS & {t.upper() for t in headline.tickers}
        or "bitcoin" in title
        or "ethereum" in title
    ):
        return True
    return False


def _headline_targets_asset(headline: NewsHeadline, asset: str) -> bool:
    if asset == "USD":
        return False
    tickers = {t.upper() for t in headline.tickers}
    if asset.upper() in tickers:
        return True
    title = (headline.title or "").lower()
    if asset.upper() == "ETH" and "ethereum" in title:
        return True
    if asset.upper() == "BTC" and "bitcoin" in title:
        return True
    return False


def _is_offensive_intent(intent) -> bool:
    if getattr(intent, "is_defensive", False):
        return False
    if getattr(intent, "is_accumulation", False):
        return False
    name = getattr(intent, "strategy_name", "") or ""
    if name in {"equity_dca", "whale_follow"}:
        return False
    return True


class TradeContextChecker:
    """Cached news + flow snapshot refreshed each engine tick."""

    def __init__(
        self,
        *,
        news_check_enabled: bool,
        news_block_severe: bool,
        news_block_dca: bool,
        flow_check_enabled: bool,
        flow_momentum_threshold: float,
        flow_risk_off_ratio: float,
        news_enabled: bool,
        news_provider: str,
        cryptopanic_api_key: str,
        rss_feeds: str,
        news_max_items: int,
        watch_assets: Sequence[str],
        symbol_assets: dict[str, str],
    ):
        self.news_check_enabled = news_check_enabled
        self.news_block_severe = news_block_severe
        self.news_block_dca = news_block_dca
        self.flow_check_enabled = flow_check_enabled
        self.flow_momentum_threshold = flow_momentum_threshold
        self.flow_risk_off_ratio = flow_risk_off_ratio
        self._news_enabled = news_enabled
        self._news_provider = news_provider
        self._cryptopanic_api_key = cryptopanic_api_key
        self._rss_feeds = rss_feeds
        self._news_max_items = news_max_items
        self._watch_assets = tuple(watch_assets)
        self._symbol_assets = symbol_assets
        self._news_client: NewsClient | None = None
        self._headlines: list[NewsHeadline] = []
        self._flow: MarketFlowSnapshot | None = None

    def refresh(self, candles: dict) -> None:
        if self.flow_check_enabled:
            self._flow = compute_market_flow(
                candles,
                self._symbol_assets,
                momentum_threshold=self.flow_momentum_threshold,
                risk_off_ratio=self.flow_risk_off_ratio,
            )
        if self.news_check_enabled and self._news_enabled:
            self._refresh_news()

    @property
    def flow(self) -> MarketFlowSnapshot | None:
        return self._flow

    @property
    def headlines(self) -> list[NewsHeadline]:
        return list(self._headlines)

    def _news_client_instance(self) -> NewsClient | None:
        if self._news_client is not None:
            return self._news_client
        try:
            self._news_client = NewsClient(
                providers=self._news_provider,
                api_key=self._cryptopanic_api_key or "",
                rss_feeds=parse_rss_feed_env(self._rss_feeds),
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to build NewsClient for trade context")
            return None
        return self._news_client

    def _refresh_news(self) -> None:
        client = self._news_client_instance()
        if client is None:
            return
        try:
            self._headlines = client.fetch_headlines(
                self._watch_assets, self._news_max_items
            )
        except Exception:  # noqa: BLE001
            logger.warning("Trade-context news fetch failed", exc_info=True)

    def check_intent(self, intent) -> TradeContextGate:
        if not _is_offensive_intent(intent):
            return TradeContextGate(True)

        if self.flow_check_enabled and self._flow and self._flow.regime == "risk_off":
            if intent.to_asset != "USD":
                return TradeContextGate(
                    False,
                    (
                        f"Market flow risk-off ({self._flow.negative_ratio:.0%} assets weak) "
                        f"— blocked {intent.from_asset}->{intent.to_asset}"
                    ),
                )

        if not self.news_check_enabled or not self.news_block_severe:
            return TradeContextGate(True)

        if (
            getattr(intent, "is_accumulation", False)
            or getattr(intent, "strategy_name", "") == "equity_dca"
        ) and not self.news_block_dca:
            return TradeContextGate(True)

        for headline in self._headlines:
            if not _headline_is_severe(headline):
                continue
            for asset in (intent.to_asset, intent.from_asset):
                if _headline_targets_asset(headline, asset):
                    snippet = (headline.title or "")[:80]
                    return TradeContextGate(
                        False,
                        f"News gate — severe headline for {asset}: {snippet}",
                    )
        return TradeContextGate(True)
