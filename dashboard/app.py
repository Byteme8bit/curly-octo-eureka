"""FastAPI application — read-only local dashboard."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from dashboard.config import load_settings
from dashboard.parsers import build_auditor_view, build_tradebot_view, build_watchdog_view
from dashboard.parsers.series import build_forecasts, build_portfolio_history, build_trades_series
from dashboard.parsers.timeline import build_timeline
from dashboard.service import build_overview, normalize_mode
from dashboard.parsers.whales import build_whale_view

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app() -> FastAPI:
    settings = load_settings()
    app = FastAPI(
        title="TradeBot Local Dashboard",
        description="Read-only trader cockpit for TradeBot, Watchdog, and Auditor.",
        version="0.3.0",
    )

    @app.get("/api/meta")
    def api_meta() -> dict:
        return {
            "refresh_seconds": settings.refresh_seconds,
            "host": settings.host,
            "port": settings.port,
            "root": str(settings.root),
            "live_enabled": settings.live_enabled,
            "mirror_mode": settings.live_mirror_paper and settings.live_enabled,
            "modes": ["paper", "live"],
        }

    def _overview(mode: str):
        return build_overview(settings, mode=normalize_mode(mode))

    def _portfolio_history(mode: str):
        return build_portfolio_history(settings, mode=normalize_mode(mode))

    def _trades_series(mode: str):
        return build_trades_series(settings, mode=normalize_mode(mode))

    def _tradebot(mode: str):
        return build_tradebot_view(settings, mode=normalize_mode(mode))

    @app.get("/api/overview")
    def api_overview(mode: str = Query("paper")) -> dict:
        return _overview(mode)

    @app.get("/api/paper/overview")
    def api_paper_overview() -> dict:
        return _overview("paper")

    @app.get("/api/live/overview")
    def api_live_overview() -> dict:
        return _overview("live")

    @app.get("/api/portfolio/history")
    def api_portfolio_history(mode: str = Query("paper")) -> dict:
        return _portfolio_history(mode)

    @app.get("/api/paper/portfolio/history")
    def api_paper_portfolio_history() -> dict:
        return _portfolio_history("paper")

    @app.get("/api/live/portfolio/history")
    def api_live_portfolio_history() -> dict:
        return _portfolio_history("live")

    @app.get("/api/trades/series")
    def api_trades_series(mode: str = Query("paper")) -> dict:
        return _trades_series(mode)

    @app.get("/api/paper/trades/series")
    def api_paper_trades_series() -> dict:
        return _trades_series("paper")

    @app.get("/api/live/trades/series")
    def api_live_trades_series() -> dict:
        return _trades_series("live")

    @app.get("/api/forecasts")
    def api_forecasts() -> dict:
        return build_forecasts(settings)

    @app.get("/api/timeline")
    def api_timeline(mode: str = Query("paper")) -> dict:
        tb = build_tradebot_view(settings, mode=normalize_mode(mode))
        drawdown = 0.0
        if tb.get("portfolio"):
            drawdown = float(tb["portfolio"].get("drawdown_pct", 0.0))
        watchdog = build_watchdog_view(settings, drawdown_pct=drawdown)
        auditor = build_auditor_view(settings)
        return build_timeline(
            settings,
            tradebot=tb,
            watchdog=watchdog,
            auditor=auditor,
        )

    @app.get("/api/tradebot")
    def api_tradebot(mode: str = Query("paper")) -> dict:
        return _tradebot(mode)

    @app.get("/api/paper/tradebot")
    def api_paper_tradebot() -> dict:
        return _tradebot("paper")

    @app.get("/api/live/tradebot")
    def api_live_tradebot() -> dict:
        return _tradebot("live")

    @app.get("/api/watchdog")
    def api_watchdog(mode: str = Query("paper")) -> dict:
        tb = build_tradebot_view(settings, mode=normalize_mode(mode))
        dd = 0.0
        if tb.get("portfolio"):
            dd = float(tb["portfolio"].get("drawdown_pct", 0.0))
        return build_watchdog_view(settings, drawdown_pct=dd)

    @app.get("/api/auditor")
    def api_auditor() -> dict:
        return build_auditor_view(settings)

    @app.get("/api/whales")
    def api_whales() -> dict:
        return build_whale_view(settings)

    @app.get("/")
    @app.get("/paper")
    def paper_index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/live")
    def live_index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    return app


app = create_app()
