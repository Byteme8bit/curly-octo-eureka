"""Safety gates for real-money Kraken execution."""

from __future__ import annotations

from bot.markets import TradeRoute

LIVE_CONFIRM_PHRASE = "I_ACCEPT_REAL_MONEY"

# Balances synced from Kraken when live is armed (crypto defaults).
LIVE_SYNC_ASSETS = frozenset({"ETH", "ADA", "USD", "BTC"})

# BTC may appear only as a bridge leg between allowed assets.
LIVE_BRIDGE_ASSETS = frozenset({"BTC"})


def build_live_sync_assets(
    allowed_assets: tuple[str, ...],
    equity_assets: frozenset[str] | None = None,
) -> frozenset[str]:
    """Assets to refresh from Kraken balances during live execution."""
    sync = set(LIVE_SYNC_ASSETS) | set(allowed_assets)
    if equity_assets:
        sync.update(a for a in allowed_assets if a in equity_assets)
    return frozenset(sync)


def parse_allowed_assets(raw: str) -> tuple[str, ...]:
    assets = tuple(a.strip().upper() for a in raw.split(",") if a.strip())
    return assets or ("ETH", "ADA")


def is_live_armed(*, live_enabled: bool, live_trading_confirm: str) -> bool:
    return live_enabled and live_trading_confirm == LIVE_CONFIRM_PHRASE


def _route_assets(route: TradeRoute) -> frozenset[str]:
    assets: set[str] = set()
    for leg in route.legs:
        assets.add(leg.pair.base)
        assets.add(leg.pair.quote)
    return frozenset(assets)


def check_live_route(
    route: TradeRoute,
    allowed_assets: tuple[str, ...],
    *,
    allow_triangular: bool = False,
    max_route_legs: int = 1,
) -> tuple[bool, str]:
    """Return (allowed, reason).

    Default (triangular off): single-hop */USD only among allowed assets.
    With LIVE_ALLOW_TRIANGULAR=1: sequential multi-hop among ETH/ADA/USD (+ BTC bridge).
    """
    if route.hops > max_route_legs:
        return (
            False,
            f"Route has {route.hops} legs — LIVE_MAX_ROUTE_LEGS={max_route_legs}",
        )

    if route.hops > 1 and not allow_triangular:
        return (
            False,
            "Live trading blocks multi-hop routes (set LIVE_ALLOW_TRIANGULAR=1)",
        )

    allowed = frozenset(allowed_assets) | {"USD"} | LIVE_BRIDGE_ASSETS
    for asset in _route_assets(route):
        if asset not in allowed:
            return (
                False,
                f"Live route asset {asset} not allowed "
                f"(LIVE_ALLOWED_ASSETS={','.join(allowed_assets)} + USD + BTC bridge)",
            )

    if not allow_triangular:
        for leg in route.legs:
            if leg.pair.quote != "USD":
                return (
                    False,
                    f"Live v1 only supports */USD pairs — blocked {leg.pair.symbol}",
                )

    return True, ""
