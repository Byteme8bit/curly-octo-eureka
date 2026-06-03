"""Run the local dashboard: ``python -m dashboard``."""

from __future__ import annotations

import uvicorn

from dashboard.config import load_settings


def main() -> None:
    settings = load_settings()
    uvicorn.run(
        "dashboard.app:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
