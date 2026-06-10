"""FastAPI application — read-only local dashboard."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from dashboard.config import load_settings
from dashboard.parsers import build_auditor_view, build_tradebot_view, build_watchdog_view
from dashboard.parsers.series import build_forecasts, build_portfolio_history, build_trades_series
from dashboard.parsers.timeline import build_timeline
from dashboard.service import build_overview
from dashboard.parsers.whales import build_whale_view

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app() -> FastAPI:
    settings = load_settings()
    app = FastAPI(
        title="TradeBot Local Dashboard",
        description="Read-only trader cockpit for TradeBot, Watchdog, and Auditor.",
        version="0.2.0",
    )

    @app.get("/api/meta")
    def api_meta() -> dict:
        return {
            "refresh_seconds": settings.refresh_seconds,
            "host": settings.host,
            "port": settings.port,
            "root": str(settings.root),
        }

    @app.get("/api/overview")
    def api_overview() -> dict:
        return build_overview(settings)

    @app.get("/api/portfolio/history")
    def api_portfolio_history() -> dict:
        return build_portfolio_history(settings)

    @app.get("/api/trades/series")
    def api_trades_series() -> dict:
        return build_trades_series(settings)

    @app.get("/api/forecasts")
    def api_forecasts() -> dict:
        return build_forecasts(settings)

    @app.get("/api/timeline")
    def api_timeline() -> dict:
        return build_timeline(settings)

    @app.get("/api/tradebot")
    def api_tradebot() -> dict:
        return build_tradebot_view(settings)

    @app.get("/api/watchdog")
    def api_watchdog() -> dict:
        tb = build_tradebot_view(settings)
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
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    return app


app = create_app()
