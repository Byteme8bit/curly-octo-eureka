"""Watchdog configuration — monitors the paper trading bot from the filesystem."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

WATCHDOG_DIR = Path(__file__).resolve().parent
BOT_ROOT = WATCHDOG_DIR.parent

load_dotenv(BOT_ROOT / ".env")
load_dotenv(WATCHDOG_DIR / ".env")


@dataclass(frozen=True)
class WatchdogSettings:
    enabled: bool
    poll_seconds: int
    stale_minutes: float
    discord_webhook: str
    discord_pin_major: bool
    trade_usd_threshold: float
    pnl_pct_threshold: float
    drawdown_warn_pct: float
    error_cooldown_minutes: float
    auto_pause_score: int
    error_burst_count: int
    error_burst_minutes: float
    heartbeat_minutes: float
    quiet_mode: bool
    error_pin_count: int
    error_pin_window_minutes: float
    milestone_cooldown_minutes: float
    live_enabled: bool
    live_state_file: Path
    live_session_start_file: Path
    paper_portfolio_file: Path
    bot_root: Path
    log_dir: Path
    receipts_dir: Path
    state_file: Path
    runtime_log: Path
    diagnostics_dir: Path
    watchdog_state_file: Path


def load_settings() -> WatchdogSettings:
    root = Path(os.getenv("WATCHDOG_BOT_ROOT", str(BOT_ROOT)))
    log_dir = Path(os.getenv("WATCHDOG_LOG_DIR", str(root / "logs")))
    # Integrated mode (python main.py) posts via the trade bot's Discord — this webhook
    # is only used for optional standalone mode (python watchdog/main.py).
    discord_webhook = (
        os.getenv("WATCHDOG_DISCORD_WEBHOOK", "").strip()
        or os.getenv("DISCORD_WEBHOOK", "").strip()
        or os.getenv("ALERT_DISCORD_WEBHOOK", "").strip()
    )
    quiet = os.getenv("WATCHDOG_QUIET_MODE", os.getenv("DISCORD_QUIET_MODE", "0")) == "1"
    hb_raw = os.getenv("WATCHDOG_HEARTBEAT_MINUTES")
    if hb_raw is not None and str(hb_raw).strip() != "":
        heartbeat_minutes = float(hb_raw)
    elif quiet:
        heartbeat_minutes = 0.0
    else:
        heartbeat_minutes = 15.0
    return WatchdogSettings(
        enabled=os.getenv("WATCHDOG_ENABLED", "1") == "1",
        poll_seconds=int(os.getenv("WATCHDOG_POLL_SECONDS", "10")),
        stale_minutes=float(os.getenv("WATCHDOG_STALE_MINUTES", "5")),
        discord_webhook=discord_webhook,
        discord_pin_major=os.getenv("WATCHDOG_PIN_MAJOR", "1") == "1",
        trade_usd_threshold=float(os.getenv("WATCHDOG_TRADE_USD", "25")),
        pnl_pct_threshold=float(os.getenv("WATCHDOG_PNL_PCT", "0.05")),
        drawdown_warn_pct=float(os.getenv("WATCHDOG_DRAWDOWN_WARN_PCT", "0.10")),
        error_cooldown_minutes=float(os.getenv("WATCHDOG_ERROR_COOLDOWN_MINUTES", "15")),
        auto_pause_score=int(os.getenv("WATCHDOG_AUTO_PAUSE_SCORE", "25")),
        error_burst_count=int(os.getenv("WATCHDOG_ERROR_BURST_COUNT", "5")),
        error_burst_minutes=float(os.getenv("WATCHDOG_ERROR_BURST_MINUTES", "10")),
        heartbeat_minutes=heartbeat_minutes,
        quiet_mode=quiet,
        error_pin_count=int(os.getenv("DISCORD_ERROR_PIN_COUNT", "3")),
        error_pin_window_minutes=float(os.getenv("DISCORD_ERROR_PIN_WINDOW_MINUTES", "30")),
        milestone_cooldown_minutes=float(os.getenv("WATCHDOG_MILESTONE_COOLDOWN_MINUTES", "60")),
        live_enabled=os.getenv("LIVE_ENABLED", "0") == "1",
        live_state_file=root / os.getenv("LIVE_STATE_FILE", ".live_state.json"),
        live_session_start_file=root / "live_session_start.json",
        paper_portfolio_file=root / os.getenv("PAPER_PORTFOLIO_FILE", "paper_portfolio.json"),
        bot_root=root,
        log_dir=log_dir,
        receipts_dir=Path(os.getenv("WATCHDOG_RECEIPTS_DIR", str(root / "receipts"))),
        state_file=Path(os.getenv("WATCHDOG_PAPER_STATE", str(root / ".paper_state.json"))),
        runtime_log=Path(os.getenv("WATCHDOG_RUNTIME_LOG", str(log_dir / "runtime.log"))),
        diagnostics_dir=Path(os.getenv("WATCHDOG_DIAGNOSTICS_DIR", str(root / "diagnostics"))),
        watchdog_state_file=root / ".watchdog_state.json",
    )
