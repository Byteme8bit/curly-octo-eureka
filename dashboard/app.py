"""FastAPI application — read-only local dashboard."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from dashboard.config import load_settings
from dashboard.parsers import build_auditor_view, build_tradebot_view, build_watchdog_view
from dashboard.service import build_overview

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app() -> FastAPI:
    settings = load_settings()
    app = FastAPI(
        title="TradeBot Local Dashboard",
        description="Read-only view of TradeBot, Watchdog, and Auditor activity.",
        version="0.1.0",
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

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    return app


app = create_app()
