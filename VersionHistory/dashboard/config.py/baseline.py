"""Dashboard paths and server settings (read-only; does not load secrets)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class DashboardSettings:
    root: Path
    host: str
    port: int
    refresh_seconds: int
    paper_portfolio_file: Path
    paper_state_file: Path
    watchdog_state_file: Path
    auditor_state_file: Path
    runtime_overrides_file: Path
    log_dir: Path
    runtime_log: Path
    discord_chat_log: Path
    receipts_dir: Path
    reports_dir: Path
    backlog_file: Path
    # Watchdog health computation (mirrors watchdog/config defaults)
    error_burst_count: int
    error_burst_minutes: float
    auto_pause_score: int


def load_settings() -> DashboardSettings:
    root = Path(os.getenv("DASHBOARD_BOT_ROOT", str(ROOT)))
    log_dir = Path(os.getenv("DASHBOARD_LOG_DIR", str(root / "logs")))
    return DashboardSettings(
        root=root,
        host=os.getenv("DASHBOARD_HOST", "127.0.0.1"),
        port=int(os.getenv("DASHBOARD_PORT", "8765")),
        refresh_seconds=int(os.getenv("DASHBOARD_REFRESH_SECONDS", "15")),
        paper_portfolio_file=root / os.getenv("PAPER_PORTFOLIO_FILE", "paper_portfolio.json"),
        paper_state_file=root / ".paper_state.json",
        watchdog_state_file=root / ".watchdog_state.json",
        auditor_state_file=root / ".auditor_state.json",
        runtime_overrides_file=root / "runtime_overrides.json",
        log_dir=log_dir,
        runtime_log=log_dir / "runtime.log",
        discord_chat_log=Path(
            os.getenv("DISCORD_CHAT_LOG_FILE", str(log_dir / "discord_chat.log"))
        ),
        receipts_dir=root / "receipts",
        reports_dir=root / os.getenv("AUDITOR_REPORTS_DIR", "reports"),
        backlog_file=root / "BACKLOG.md",
        error_burst_count=int(os.getenv("WATCHDOG_ERROR_BURST_COUNT", "5")),
        error_burst_minutes=float(os.getenv("WATCHDOG_ERROR_BURST_MINUTES", "10")),
        auto_pause_score=int(os.getenv("WATCHDOG_AUTO_PAUSE_SCORE", "25")),
    )
