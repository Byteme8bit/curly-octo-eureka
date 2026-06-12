"""Background watchdog — started/stopped with the trading bot process."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from bot.local_time import format_pacific
from bot.runtime import BotRuntime
from config import Settings
from watchdog.config import load_settings as load_watchdog_settings
from watchdog.engine import WatchdogEngine

logger = logging.getLogger(__name__)


class WatchdogService:
    """Runs WatchdogEngine in a daemon thread tied to TradingEngine lifecycle."""

    def __init__(
        self,
        settings: Settings,
        runtime: BotRuntime,
        *,
        post_alert: Callable[[str, bool], None] | None = None,
        is_trading_active: Callable[[], bool] | None = None,
        pause_trading: Callable[[], None] | None = None,
    ):
        wd_settings = load_watchdog_settings()
        self.enabled = wd_settings.enabled
        self.poll_seconds = wd_settings.poll_seconds
        self._runtime = runtime
        self._post_alert = post_alert
        self._is_trading_active = is_trading_active or runtime.is_trading_active
        self._pause_trading = pause_trading or (lambda: runtime.set_trading_active(False))
        self._engine = WatchdogEngine(
            wd_settings,
            post_alert=self._alert,
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_auto_pause_at = 0.0

    def _alert(self, message: str, pin: bool = False) -> None:
        if self._post_alert:
            self._post_alert(message, pin)
        else:
            logger.warning("Watchdog alert: %s", message.replace("\n", " ")[:200])

    def _request_pause(self, reason: str, *, auto: bool = False) -> bool:
        if not self._is_trading_active():
            return False
        self._pause_trading()
        self._engine.record_pause(reason, auto=auto)
        headline = "**Watchdog auto-paused trade bot**" if auto else "**Watchdog paused trade bot**"
        self._alert(
            f"{headline}\n{reason}\n\n"
            "Only the owner can resume — send `start` in this channel.",
            pin=True,
        )
        return True

    def start(self) -> None:
        if not self.enabled:
            logger.info("Watchdog disabled (WATCHDOG_ENABLED=0)")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._engine.begin_session()
        self._engine.prime()
        self._alert(self._engine.startup_message(), pin=False)
        self._thread = threading.Thread(target=self._loop, name="watchdog", daemon=True)
        self._thread.start()
        logger.info("Watchdog thread started")

    def stop(self) -> None:
        if not self.enabled:
            return
        if self._stop.is_set() and not (self._thread and self._thread.is_alive()):
            return
        self._stop.set()
        # Tell the engine to abort the in-progress poll between alert posts so
        # we don't wait the full Discord HTTP timeout for every queued alert.
        self._engine.request_stop()
        thread = self._thread
        if thread and thread.is_alive():
            # Short join: alerts inside the loop check the engine stop flag.
            thread.join(timeout=5)
            if thread.is_alive():
                logger.warning(
                    "Watchdog thread did not stop within 5s; it is a daemon and "
                    "will be terminated when the process exits."
                )
        self._thread = None
        self._engine.end_session()
        logger.info("Watchdog thread stopped")

    def reset(self, *, silent: bool = False) -> None:
        self._engine.reset_session()
        if not silent:
            self._alert(
                "**Watchdog reset** — health score and error counters cleared for new paper session.",
                pin=False,
            )

    def status_text(self) -> str:
        return self._engine.format_status(
            trading_active=self._is_trading_active(),
            bot_process_running=not self._stop.is_set() and bool(self._thread and self._thread.is_alive()),
        )

    def pause_bot(self, reason: str = "Manual watchdog pause via Discord") -> str:
        if not self.enabled:
            return "Watchdog is disabled."
        if not self._is_trading_active():
            report = self._engine.health_report()
            return (
                "Trade bot is **already paused**.\n"
                + "\n".join(report.summary_lines())
                + "\n\nSend `start` to resume (owner only)."
            )
        self._request_pause(reason, auto=False)
        report = self._engine.health_report()
        return (
            "Watchdog paused the trade bot.\n"
            + "\n".join(report.summary_lines())
            + "\n\nSend `start` to resume (owner only)."
        )

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._engine.poll_once()
                report = self._engine.health_report()
                if report.auto_pause_recommended and self._is_trading_active():
                    now = time.monotonic()
                    if now - self._last_auto_pause_at > 300:
                        self._last_auto_pause_at = now
                        self._request_pause(report.auto_pause_reason, auto=True)
            except Exception:
                logger.exception("Watchdog poll failed")
            self._stop.wait(self.poll_seconds)
