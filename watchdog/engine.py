"""Watchdog engine — polls logs, receipts, state, and diagnostics."""



from __future__ import annotations



import logging

import time

from datetime import datetime, timezone

from pathlib import Path

from typing import Callable



from bot.live_portfolio import load_live_portfolio_snapshot
from bot.local_time import format_pacific
from bot.report import pnl_milestone_band
from watchdog.alerter import DiscordAlerter

from watchdog.config import WatchdogSettings

from watchdog.parsers import (

    TradeEvent,

    load_paper_state,

    parse_portfolio_line,

    parse_receipt,

    parse_runtime_errors,

    extract_action_context,

    read_log_tail,

)

from watchdog.scoring import HealthReport, compute_health

from watchdog.state import WatchdogState



logger = logging.getLogger(__name__)





class WatchdogEngine:

    def __init__(

        self,

        settings: WatchdogSettings,

        *,

        post_alert: Callable[[str, bool], None] | None = None,

    ):

        self.settings = settings

        self._post_alert = post_alert

        self.alerter = DiscordAlerter(

            settings.discord_webhook, pin_major=settings.discord_pin_major

        )

        self.state = WatchdogState.load(settings.watchdog_state_file)

        self._last_drawdown = 0.0

        self._hibernating = False

        self._reevaluation = False

        self._stop_requested = False



    def request_stop(self) -> None:

        """Signal the engine to abort the in-progress poll quickly."""

        self._stop_requested = True



    def _save(self) -> None:

        self.state.save(self.settings.watchdog_state_file)



    def _alert(self, message: str, *, pin: bool = False) -> None:

        if self._post_alert:

            self._post_alert(message, pin=pin)

        elif self.alerter.enabled:

            self.alerter.post(message, pin=pin)



    def begin_session(self) -> None:

        self.state.running = True

        self._stop_requested = False

        self.state.session_started_at = format_pacific()

        # Reset counters whose name implies "this bot process" — without this,
        # trades_session etc. accumulate across restarts and the health score
        # drifts down forever even on a clean restart (the >40-trade penalty
        # in particular would pin the score at 90/100 indefinitely).
        # Error timestamps and dedup state are intentionally preserved so a
        # crash-loop bot still scores low and we don't re-alert old errors.

        self.state.reset_process_session_counters()

        # Reset heartbeat anchor so first heartbeat fires after `heartbeat_minutes`

        # of fresh runtime (not based on stale value from a prior session).

        self.state.last_heartbeat_at = time.time()

        self._save()



    def end_session(self) -> None:

        self.state.running = False

        self._save()



    def reset_session(self) -> None:

        self.state.reset_session()

        self._last_drawdown = 0.0

        self._save()



    def record_pause(self, reason: str, *, auto: bool = False) -> None:

        self.state.record_watchdog_pause()

        self.state.last_watchdog_pause_at = format_pacific()

        self._save()



    def prime(self) -> None:

        for path in self._current_session_logs():

            self.state.read_new_bytes(path)

        if self.settings.runtime_log.exists():

            self.state.read_new_bytes(self.settings.runtime_log)

        for path in self.settings.receipts_dir.glob("*.txt"):

            self.state.mark_receipt_seen(path.name)

        if self.settings.diagnostics_dir.exists():

            for path in self.settings.diagnostics_dir.glob("circuit_breaker_*.json"):

                self.state.mark_diagnostic_seen(path.name)

        self.state.last_log_activity = time.time()

        self.state.prune_errors()

        self._save()



    def health_report(self) -> HealthReport:

        self.state.prune_errors()

        return compute_health(

            error_timestamps=self.state.error_timestamps,

            watchdog_error_timestamps=self.state.watchdog_error_timestamps,

            drawdown_pct=self._last_drawdown,

            trades_session=self.state.trades_session,

            reevaluation_mode=self._reevaluation,

            hibernating=self._hibernating,

            stale_alert=self.state.stale_alert_sent,

            watchdog_pauses=self.state.watchdog_pause_count,

            error_burst_count=self.settings.error_burst_count,

            error_burst_minutes=self.settings.error_burst_minutes,

            auto_pause_score=self.settings.auto_pause_score,

        )



    def format_status(self, *, trading_active: bool, bot_process_running: bool) -> str:

        report = self.health_report()

        wd_state = "RUNNING" if self.state.running and bot_process_running else "STOPPED"

        tb_state = "TRADING" if trading_active else "PAUSED"

        lines = [

            "**Watchdog status**",

            f"Watchdog: **{wd_state}**  |  Trade bot: **{tb_state}**",

        ]

        if self.state.session_started_at:

            lines.append(f"Session since: {self.state.session_started_at}")

        lines.extend(report.summary_lines())

        if report.score < 40:

            lines.append("")

            lines.append("_Recommendation: review before sending `start`. Watchdog may auto-pause on error bursts._")

        return "\n".join(lines)



    def _current_session_logs(self) -> list[Path]:

        if not self.settings.log_dir.exists():

            return []

        logs = sorted(

            self.settings.log_dir.glob("*_PDT.log"),

            key=lambda p: p.stat().st_mtime,

        )

        return logs[-2:]



    def _session_log_context(self) -> str:

        logs = self._current_session_logs()

        if not logs:

            return ""

        return read_log_tail(logs[-1])



    def _check_runtime_log(self) -> list[tuple[str, bool]]:

        alerts: list[tuple[str, bool]] = []

        path = self.settings.runtime_log

        chunk = self.state.read_new_bytes(path).decode("utf-8", errors="replace")

        if not chunk:

            return alerts

        self.state.last_log_activity = time.time()

        cooldown = self.settings.error_cooldown_minutes * 60

        context_text = self._session_log_context()

        pin_window = self.settings.error_pin_window_minutes * 60
        for err in parse_runtime_errors(chunk):
            is_watchdog_self = err.message.startswith("Watchdog ")
            source = "watchdog" if is_watchdog_self else "bot"

            self.state.record_error(source=source)

            record = {

                "at": err.at,

                "level": err.level,

                "source": source,

                "message": err.message[:500],

                "context": extract_action_context(context_text),

            }

            self.state.append_error(record)

            # Watchdog self-errors are tracked for visibility but not posted

            # (the user already sees them via runtime.log noise).

            if is_watchdog_self:

                continue

            key = f"{err.level}:{err.message[:120]}"

            if not self.state.should_alert_error(key, cooldown):

                continue

            pin = self.state.track_error_for_pin(
                key,
                window_sec=pin_window,
                threshold=self.settings.error_pin_count,
            )

            label = "pinned" if pin else "not pinned yet"

            alerts.append((
                f"**Watchdog — trading bot {err.level}** ({label})\n"
                f"`{err.message[:500]}`\n"
                f"_Pin triggers after >{self.settings.error_pin_count} repeats in "
                f"{self.settings.error_pin_window_minutes:.0f}m. "
                f"See `logs/runtime.log`._",
                pin,
            ))

        return alerts



    def _check_session_logs(self) -> list[tuple[str, bool]]:

        alerts: list[tuple[str, bool]] = []

        for path in self._current_session_logs():

            chunk = self.state.read_new_bytes(path).decode("utf-8", errors="replace")

            if not chunk:

                continue

            self.state.last_log_activity = time.time()

            for line in chunk.splitlines():

                snap = parse_portfolio_line(line)

                if not snap:

                    continue

                self.state.last_portfolio = snap.portfolio

                self._last_drawdown = snap.drawdown_pct

                if not self.settings.live_enabled:
                    alerts.extend(self._portfolio_alerts(snap))

        return alerts



    def _portfolio_alerts(self, snap) -> list[tuple[str, bool]]:
        return self._portfolio_alerts_for(
            portfolio=snap.portfolio,
            pnl=snap.pnl,
            drawdown_pct=snap.drawdown_pct,
            baseline=self.state.last_baseline or snap.portfolio - snap.pnl,
            source="paper",
        )

    def _portfolio_alerts_for(
        self,
        *,
        portfolio: float,
        pnl: float,
        drawdown_pct: float,
        baseline: float,
        source: str,
    ) -> list[tuple[str, bool]]:
        alerts: list[tuple[str, bool]] = []

        if self.settings.quiet_mode:
            return alerts

        if baseline > 0 and source == "live":
            self.state.last_baseline = baseline

        threshold = self.settings.pnl_pct_threshold
        band = pnl_milestone_band(pnl, baseline, threshold)
        last_band = (
            self.state.last_live_pnl_band if source == "live" else self.state.last_pnl_band
        )
        if band != 0 and band != last_band:
            cooldown_sec = self.settings.milestone_cooldown_minutes * 60
            now = time.time()
            if now - self.state.last_milestone_alert_at >= cooldown_sec:
                if source == "live":
                    self.state.last_live_pnl_band = band
                else:
                    self.state.last_pnl_band = band
                self.state.last_milestone_alert_at = now
                pct = (pnl / baseline * 100) if baseline > 0 else 0.0
                direction = "gain" if band > 0 else "loss"
                if source == "live":
                    portfolio_line = (
                        f"Live Kraken spot: ${portfolio:,.2f}  |  "
                        f"Session PnL: ${pnl:+,.2f} ({pct:+.1f}%)"
                    )
                else:
                    portfolio_line = (
                        f"[Paper sim] Portfolio ${portfolio:,.2f}  |  "
                        f"PnL {pnl:+.2f} ({pct:+.1f}%)"
                    )
                alerts.append((
                    f"**Watchdog — major portfolio {direction}**\n"
                    f"{portfolio_line}\n"
                    f"Crossed {abs(band) * threshold:.0%} milestone threshold",
                    True,
                ))

        if drawdown_pct >= self.settings.drawdown_warn_pct:
            if drawdown_pct > self.state.last_drawdown_warn + 0.01:
                self.state.last_drawdown_warn = drawdown_pct
                label = "Live Kraken spot" if source == "live" else "Portfolio"
                alerts.append((
                    f"**Watchdog — drawdown warning**\n"
                    f"{label} ${portfolio:,.2f}  |  "
                    f"drawdown {drawdown_pct:.1%} from peak\n"
                    f"Circuit breaker triggers at 15% — review holdings.",
                    False,
                ))
        elif drawdown_pct < self.settings.drawdown_warn_pct * 0.5:
            self.state.last_drawdown_warn = 0.0

        return alerts

    def _check_live_portfolio(self) -> list[tuple[str, bool]]:
        alerts: list[tuple[str, bool]] = []
        if not self.settings.live_enabled:
            return alerts
        snap = load_live_portfolio_snapshot(
            live_state_file=self.settings.live_state_file,
            live_session_start_file=self.settings.live_session_start_file,
            paper_portfolio_file=self.settings.paper_portfolio_file,
        )
        if snap is None:
            return alerts
        self.state.last_portfolio = snap.portfolio_usd
        self._last_drawdown = snap.drawdown_pct
        self.state.last_log_activity = time.time()
        alerts.extend(
            self._portfolio_alerts_for(
                portfolio=snap.portfolio_usd,
                pnl=snap.session_pnl,
                drawdown_pct=snap.drawdown_pct,
                baseline=snap.baseline_portfolio_usd,
                source="live",
            )
        )
        return alerts



    def _record_trade_from_receipt(self, trade: TradeEvent) -> None:
        """Track session trade count for health scoring only.

        TradeBot already posts trade execution to Discord; WatchDog does not
        duplicate routine trade alerts.
        """
        del trade  # receipt parsed for bookkeeping only
        self.state.record_trade()

    def _check_receipts(self) -> list[tuple[str, bool]]:

        alerts: list[tuple[str, bool]] = []

        if not self.settings.receipts_dir.exists():

            return alerts

        receipts = sorted(

            self.settings.receipts_dir.glob("*.txt"),

            key=lambda p: p.stat().st_mtime,

        )

        for path in receipts[-20:]:

            if not self.state.mark_receipt_seen(path.name):

                continue

            trade = parse_receipt(path)

            if trade:

                self._record_trade_from_receipt(trade)

        return alerts



    def _check_paper_state(self) -> list[tuple[str, bool]]:

        alerts: list[tuple[str, bool]] = []

        data = load_paper_state(self.settings.state_file)

        if not data:

            return alerts



        risk = data.get("risk", {})

        baseline = float(risk.get("baseline_portfolio", 0.0))

        peak = float(risk.get("peak_portfolio", 0.0))

        if baseline > 0 and not self.settings.live_enabled:

            self.state.last_baseline = baseline



        self._reevaluation = bool(risk.get("reevaluation_mode"))

        if self._reevaluation and not self.state.reevaluation_alerted:

            self.state.reevaluation_alerted = True

            at = risk.get("circuit_breaker_at", "unknown")

            alerts.append((
                f"**Watchdog — CIRCUIT BREAKER / re-evaluation mode**\n"
                f"Trading bot halted automated trading at {at}.\n"
                f"Peak ${peak:,.2f} — send `resume-trading` then `start` after review.",
                True,
            ))

        elif not self._reevaluation:

            self.state.reevaluation_alerted = False



        paused = risk.get("paused_until")

        self._hibernating = False

        if paused:

            try:

                until = datetime.fromisoformat(paused)

                if until > datetime.now(timezone.utc):

                    self._hibernating = True

                    key = f"hibernate:{paused}"

                    if self.state.should_alert_error(key, 3600):

                        alerts.append((
                            f"**Watchdog — bot hibernating**\n"
                            f"Paused until {until.isoformat()} (drawdown protection).",
                            False,
                        ))

            except ValueError:

                pass



        if data.get("trades"):

            self.state.last_log_activity = time.time()



        return alerts



    def _check_diagnostics(self) -> list[tuple[str, bool]]:

        alerts: list[tuple[str, bool]] = []

        if self.settings.quiet_mode:

            return alerts

        diag_dir = self.settings.diagnostics_dir

        if not diag_dir.exists():

            return alerts

        cooldown = max(self.settings.error_cooldown_minutes * 60, 3600.0)

        for path in sorted(diag_dir.glob("circuit_breaker_*.json")):

            if not self.state.mark_diagnostic_seen(path.name):

                continue

            key = f"diag:{path.name}"

            if not self.state.should_alert_error(key, cooldown):

                continue

            alerts.append((
                f"**Watchdog — circuit breaker diagnostic**\n"
                f"New file: `{path.name}`\n"
                f"Review `diagnostics/` for full state dump.",
                False,
            ))

        return alerts



    def _check_stale(self) -> list[tuple[str, bool]]:

        alerts: list[tuple[str, bool]] = []

        stale_sec = self.settings.stale_minutes * 60

        if self.state.last_log_activity <= 0:

            return alerts

        idle = time.time() - self.state.last_log_activity

        if idle >= stale_sec and not self.state.stale_alert_sent:

            self.state.stale_alert_sent = True

            alerts.append((
                f"**Watchdog — trading bot may be stalled**\n"
                f"No log activity for {idle / 60:.1f} minutes.\n"
                f"Check that `python main.py` is still running.",
                False,
            ))

        elif idle < stale_sec / 2 and self.state.stale_alert_sent:

            self.state.stale_alert_sent = False

            alerts.append((
                "**Watchdog — trading bot activity resumed**\n"
                "Log files are updating again.",
                False,
            ))

        return alerts



    def _maybe_heartbeat(self) -> str | None:

        interval = self.settings.heartbeat_minutes * 60

        if interval <= 0:

            return None

        now = time.time()

        if now - self.state.last_heartbeat_at < interval:

            return None

        self.state.last_heartbeat_at = now

        report = self.health_report()

        if self.settings.quiet_mode and report.bot_errors_last_hour == 0 and report.score >= 70:

            return None

        return self._build_heartbeat_message()



    def _build_heartbeat_message(self) -> str:

        report = self.health_report()

        bot_errors = report.bot_errors_last_hour

        wd_errors = report.watchdog_errors_last_hour

        recent = [e for e in self.state.recent_errors[-3:] if e.get("source") == "bot"]

        portfolio = self.state.last_portfolio

        if self.settings.live_enabled:
            live = load_live_portfolio_snapshot(
                live_state_file=self.settings.live_state_file,
                live_session_start_file=self.settings.live_session_start_file,
                paper_portfolio_file=self.settings.paper_portfolio_file,
            )
            if live is not None:
                portfolio_note = (
                    f"Live Kraken spot ${live.portfolio_usd:,.2f} "
                    f"(session PnL {live.session_pnl:+.2f})"
                )
            else:
                portfolio_note = "Live Kraken spot: n/a"
        else:
            portfolio_note = f"${portfolio:,.2f}" if portfolio > 0 else "n/a"

        counts = (

            f"Trade-bot errors: **{bot_errors}** last hour | "

            f"Watchdog self-errors: **{wd_errors}** last hour"

        )

        if recent:

            lines = [

                f"**Watchdog heartbeat** — issues detected (health {report.score}/100 — {report.label})",

                "",

                f"**Most recent {len(recent)} trade-bot error(s):**",

            ]

            for idx, err in enumerate(recent, 1):

                lines.append(

                    f"{idx}. `{err.get('at', '?')}` [{err.get('level', '?')}] "

                    f"{err.get('message', '')[:220]}"

                )

                context = err.get("context", "")

                if context:

                    lines.append("   _Bot actions leading up to this:_")

                    for ctx_line in context.split("\n")[:5]:

                        lines.append(f"   • {ctx_line[:160]}")

            lines.append("")

            lines.append(counts)

            lines.append(

                f"Portfolio {portfolio_note} | drawdown {report.drawdown_pct:.1%}"

            )

            return "\n".join(lines)

        return (

            f"**Watchdog heartbeat** — Everything is normal\n"

            f"Health score {report.score}/100 | Portfolio {portfolio_note} | "

            f"drawdown {report.drawdown_pct:.1%}\n"

            f"{counts}"

        )



    def poll_once(self) -> int:

        all_alerts: list[tuple[str, bool]] = []

        checks = (

            self._check_runtime_log,

            self._check_session_logs,

            self._check_receipts,

            self._check_paper_state,

            self._check_live_portfolio,

            self._check_diagnostics,

            self._check_stale,

        )

        for check in checks:

            if self._stop_requested:

                break

            try:

                all_alerts.extend(check())

            except Exception:

                logger.exception("Watchdog check %s failed", check.__name__)

        # Heartbeat in its own try block so it survives error-check failures

        try:

            heartbeat = self._maybe_heartbeat()

        except Exception:

            logger.exception("Watchdog heartbeat build failed")

            heartbeat = None

        if heartbeat:

            all_alerts.append((heartbeat, False))



        sent = 0

        try:

            for msg, explicit_pin in all_alerts:

                if self._stop_requested:

                    break

                pin = explicit_pin or (
                    "major" in msg.lower()
                    or (
                        "circuit breaker" in msg.lower()
                        and "diagnostic" not in msg.lower()
                    )
                )

                try:

                    self._alert(msg, pin=pin)

                    sent += 1

                except Exception:

                    logger.exception("Watchdog alert delivery failed")

        finally:

            self._save()

        return sent



    def startup_message(self) -> str:

        if self.settings.quiet_mode:

            return ""

        logs = self._current_session_logs()

        log_name = logs[-1].name if logs else "(none yet)"

        return (

            "**Watchdog started** — monitoring trade bot (same process)\n"

            f"Watching: session logs, `{log_name}`, receipts, "
            f"{'live + paper state' if self.settings.live_enabled else 'paper state'}, diagnostics\n"

            f"Alerts: errors, PnL ±{self.settings.pnl_pct_threshold:.0%}, "

            f"drawdown ≥{self.settings.drawdown_warn_pct:.0%}\n"

            f"Heartbeat every {self.settings.heartbeat_minutes:.0f}m\n"

            f"Send `watchdog` for status and health score | `wd pause` to pause trade bot"

        )



    def run_standalone(self) -> None:

        """Legacy entry — prefer WatchdogService inside main.py."""

        if not self.settings.enabled:

            logger.warning("Watchdog disabled (WATCHDOG_ENABLED=0)")

            return

        self.begin_session()

        self.prime()

        if self.alerter.enabled:

            self.alerter.post(self.startup_message())

        while True:

            try:

                self.poll_once()

            except Exception:

                logger.exception("Watchdog poll failed")

            time.sleep(self.settings.poll_seconds)


