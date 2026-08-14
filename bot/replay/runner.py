"""Orchestrate historical paper replay against cached OHLCV."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bot.replay.clock import ReplayClock
from bot.replay.data_provider import HistoricalDataProvider
from bot.replay.store import (
    default_symbols,
    download_replay_cache,
    load_cache,
    resolve_latest_cache,
)

logger = logging.getLogger(__name__)


def run_replay(
    *,
    settings: Any,
    build_bot,
    cache_dir: Path,
    days: int = 7,
    timeframe: str = "5m",
    duration_minutes: float = 90.0,
    asap: bool = False,
    refresh_cache: bool = True,
) -> dict:
    """
    Drive TradingBot.tick() across historical bars.

    build_bot: callable () -> TradingBot
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    symbols = default_symbols(settings.usd_symbols, getattr(settings, "stat_arb_pairs", ()))
    cache_path = resolve_latest_cache(cache_dir) if not refresh_cache else None
    if cache_path is None or refresh_cache:
        logger.info("Downloading %dd %s OHLCV for %d symbols…", days, timeframe, len(symbols))
        cache_path = download_replay_cache(
            symbols=symbols,
            timeframe=timeframe,
            days=days,
            cache_dir=cache_dir,
        )
    cache = load_cache(cache_path)
    logger.info("Loaded cache %s (%d symbols)", cache_path, len(cache.get("symbols") or {}))

    bot = build_bot()
    bot.replay_mode = True

    provider = HistoricalDataProvider(
        cache,
        usd_symbols=settings.usd_symbols,
        candle_timeframe=timeframe,
        candle_limit=settings.candle_limit,
        momentum_timeframes=settings.momentum_timeframes,
        exchange=bot.data.exchange,
    )
    if provider.bar_count < 10:
        raise RuntimeError(
            f"Insufficient replay bars ({provider.bar_count}); check OHLCV download"
        )

    clock = ReplayClock(provider.bar_timestamp(0).to_pydatetime())
    bot.data = provider
    bot.risk._now = clock.now  # type: ignore[method-assign]
    bot.governor._now = clock.now  # type: ignore[method-assign]
    if hasattr(bot.broker, "set_clock"):
        bot.broker.set_clock(clock)
    else:
        bot.broker._clock = clock  # type: ignore[attr-defined]

    n = provider.bar_count
    sleep_s = 0.0 if asap else max(0.0, (duration_minutes * 60.0) / max(1, n))
    started_wall = time.monotonic()
    trades_start = len(getattr(bot.broker.state, "trades", []) or [])

    logger.info(
        "Replay start: %d bars, sleep=%.3fs/bar, asap=%s",
        n,
        sleep_s,
        asap,
    )

    last_portfolio = 0.0
    for i in range(n):
        ts = provider.bar_timestamp(i).to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        clock.advance(ts)
        provider.set_bar(i)
        try:
            bot.tick()
        except Exception as exc:  # noqa: BLE001
            logger.exception("tick failed at bar %d (%s): %s", i, ts.isoformat(), exc)
        try:
            px = provider.fetch_usd_prices(list(bot.broker.state.balances.keys()))
            last_portfolio = bot.broker.portfolio_value(px)
        except Exception:
            pass
        if (i + 1) % 50 == 0 or i == n - 1:
            trades_now = len(bot.broker.state.trades or [])
            logger.info(
                "replay %d/%d trades=%d port=%.2f ts=%s",
                i + 1,
                n,
                trades_now - trades_start,
                last_portfolio,
                ts.isoformat(),
            )
        if sleep_s > 0:
            time.sleep(sleep_s)

    trades_end = len(bot.broker.state.trades or [])
    summary = {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "cache_path": str(cache_path),
        "bars": n,
        "days": days,
        "timeframe": timeframe,
        "duration_minutes_target": duration_minutes,
        "asap": asap,
        "wall_seconds": round(time.monotonic() - started_wall, 1),
        "trades": trades_end - trades_start,
        "trades_total": trades_end,
        "portfolio_usd": last_portfolio,
        "balances": dict(bot.broker.state.balances),
        "fee_rate": settings.fee_rate,
        "fee_force_static": getattr(settings, "fee_force_static", None),
        "paper_use_maker_fees": getattr(settings, "paper_use_maker_fees", None),
    }
    out = cache_dir / "summary.json"
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    logger.info("Replay complete: %s", summary)
    return summary
