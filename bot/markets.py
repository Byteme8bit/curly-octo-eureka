from collections import deque
from dataclasses import dataclass

import ccxt

from bot.strategies.base import Signal

MAX_ROUTE_HOPS = 3


@dataclass(frozen=True)
class PairInfo:
    symbol: str
    base: str
    quote: str


@dataclass(frozen=True)
class RouteLeg:
    pair: PairInfo
    side: Signal
    from_asset: str
    to_asset: str


@dataclass(frozen=True)
class TradeRoute:
    legs: tuple[RouteLeg, ...]

    @property
    def hops(self) -> int:
        return len(self.legs)

    @property
    def path(self) -> str:
        if not self.legs:
            return ""
        assets = [self.legs[0].from_asset]
        for leg in self.legs:
            assets.append(leg.to_asset)
        return "->".join(assets)

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(leg.pair.symbol for leg in self.legs)


class MarketRegistry:
    """Kraken market pairs for USD and crypto-to-crypto routes."""

    def __init__(
        self,
        exchange: ccxt.kraken,
        watch_assets: tuple[str, ...],
        equity_assets: frozenset[str] | None = None,
    ):
        self.watch_assets = watch_assets
        self.equity_assets = equity_assets or frozenset()
        self.pairs: dict[str, PairInfo] = {}
        self.usd_by_asset: dict[str, str] = {}
        self._load(exchange)

    def _load(self, exchange: ccxt.kraken) -> None:
        markets = exchange.load_markets()
        asset_set = set(self.watch_assets)

        for asset in self.watch_assets:
            symbol = f"{asset}/USD"
            if symbol in markets and markets[symbol].get("active", True):
                self.usd_by_asset[asset] = symbol
                self.pairs[symbol] = PairInfo(symbol=symbol, base=asset, quote="USD")

        for base in asset_set:
            if base in self.equity_assets:
                continue
            for quote in asset_set | {"USD"}:
                if base == quote:
                    continue
                symbol = f"{base}/{quote}"
                if symbol in markets and markets[symbol].get("active", True):
                    self.pairs[symbol] = PairInfo(symbol=symbol, base=base, quote=quote)

    def usd_symbols(self) -> tuple[str, ...]:
        return tuple(self.usd_by_asset[a] for a in self.watch_assets if a in self.usd_by_asset)

    def symbol_exists(self, symbol: str) -> bool:
        return symbol in self.pairs

    def _leg(self, from_asset: str, to_asset: str) -> RouteLeg | None:
        if from_asset == to_asset:
            return None

        direct = f"{to_asset}/{from_asset}"
        if direct in self.pairs:
            pair = self.pairs[direct]
            return RouteLeg(pair=pair, side=Signal.BUY, from_asset=from_asset, to_asset=to_asset)

        reverse = f"{from_asset}/{to_asset}"
        if reverse in self.pairs:
            pair = self.pairs[reverse]
            return RouteLeg(pair=pair, side=Signal.SELL, from_asset=from_asset, to_asset=to_asset)

        if from_asset == "USD" and to_asset in self.usd_by_asset:
            pair = self.pairs[self.usd_by_asset[to_asset]]
            return RouteLeg(pair=pair, side=Signal.BUY, from_asset=from_asset, to_asset=to_asset)

        if to_asset == "USD" and from_asset in self.usd_by_asset:
            pair = self.pairs[self.usd_by_asset[from_asset]]
            return RouteLeg(pair=pair, side=Signal.SELL, from_asset=from_asset, to_asset=to_asset)

        return None

    def _neighbors(self, asset: str) -> list[tuple[str, RouteLeg]]:
        options: list[tuple[str, RouteLeg]] = []
        for pair in self.pairs.values():
            if pair.quote == asset:
                leg = RouteLeg(
                    pair=pair, side=Signal.BUY, from_asset=asset, to_asset=pair.base
                )
                options.append((pair.base, leg))
            elif pair.base == asset:
                leg = RouteLeg(
                    pair=pair, side=Signal.SELL, from_asset=asset, to_asset=pair.quote
                )
                options.append((pair.quote, leg))
        return options

    def find_path(
        self, from_asset: str, to_asset: str, max_hops: int = MAX_ROUTE_HOPS
    ) -> TradeRoute | None:
        """Shortest conversion path using available Kraken pairs (BFS)."""
        if from_asset == to_asset:
            return None

        direct = self._leg(from_asset, to_asset)
        if direct:
            return TradeRoute(legs=(direct,))

        queue: deque[tuple[str, tuple[RouteLeg, ...]]] = deque([(from_asset, ())])
        visited = {from_asset}

        while queue:
            asset, legs = queue.popleft()
            if len(legs) >= max_hops:
                continue

            for next_asset, leg in self._neighbors(asset):
                new_legs = legs + (leg,)
                if next_asset == to_asset:
                    return TradeRoute(legs=new_legs)

                if next_asset not in visited:
                    visited.add(next_asset)
                    queue.append((next_asset, new_legs))

        return None

    def route(self, from_asset: str, to_asset: str) -> tuple[PairInfo, Signal] | None:
        """Backward-compatible single-hop lookup."""
        path = self.find_path(from_asset, to_asset, max_hops=1)
        if not path:
            return None
        leg = path.legs[0]
        return leg.pair, leg.side

    def all_symbols(self) -> tuple[str, ...]:
        return tuple(self.pairs.keys())
