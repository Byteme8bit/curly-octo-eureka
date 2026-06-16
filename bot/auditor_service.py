"""Auditor daemon — on-demand + scheduled + event-triggered audits.

Mirrors `WatchdogService`: a daemon thread tied to the trading engine
lifecycle, woken every 5 minutes to check the daily schedule. Audits
themselves are synchronous Python (no network — except the optional news
client, which is non-fatal). Commands from Discord call into this service
directly via the engine's command handler.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

from bot.auditor.analyzer import analyze_trades
from bot.auditor.config import AuditorConfig
from bot.auditor.context import build_audit_goal_view, load_live_audit_snapshot
from bot.auditor.forecaster import forecast_pnl
from bot.auditor.news_client import NewsClient
from bot.auditor.proposer import (
    ALLOWED_KNOBS,
    KNOB_TO_FIELD,
    build_proposal,
    knobs_with_conflicts,
    propose_changes,
)
from bot.auditor.report import (
    AuditReport,
    DISCORD_MAX_LEN,
    prepare_report_attachment,
    render_discord_summary,
    render_markdown_report,
)
from bot.auditor.runtime_overrides import (
    apply_proposal,
    list_overrides,
    revert_override,
)
from bot.auditor.state import AuditorState
from bot.local_time import format_pacific, pacific_now

logger = logging.getLogger(__name__)


class AuditorService:
    """Daemon-thread auditor with on-demand / scheduled / event triggers."""

    SCHEDULER_TICK_SECONDS = 300  # 5-minute scheduler heartbeat

    SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}

    def __init__(
        self,
        settings,
        auditor_config: AuditorConfig,
        *,
        broker,
        governor=None,
        discord=None,
        portfolio_log=None,
        watchdog_state_provider: Callable[[], dict | None] | None = None,
        overrides_file: Path | None = None,
        news_client: NewsClient | None = None,
        clock: Callable[[], object] = pacific_now,
        request_restart: Callable[[str], None] | None = None,
        live_broker_provider: Callable[[], object | None] | None = None,
    ) -> None:
        self.settings = settings
        self.config = auditor_config
        self.broker = broker
        self.governor = governor
        self.discord = discord
        self.portfolio_log = portfolio_log
        self.watchdog_state_provider = watchdog_state_provider
        self.overrides_file = overrides_file or (Path(__file__).resolve().parent.parent / "runtime_overrides.json")
        self._news_client = news_client
        self._clock = clock
        self._request_restart = request_restart
        self._live_broker_provider = live_broker_provider
        self.state = AuditorState.load(self.config.state_file)

        self._lock = threading.Lock()
        self._stop_requested = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_scheduled_day: str | None = self._scheduled_day_from_state()
        self._baseline_trade_count: int = self._current_trade_count()
        self._baseline_pnl: float | None = None

        # Conversational chat — built lazily on first `ask`/`chat` so a missing
        # API key never breaks bot startup. ``_chat_init_error`` caches the
        # reason if construction fails so subsequent calls return it quickly.
        self._chat = None
        self._chat_init_error: str | None = None

    # --------------------------------------------------------------------- lifecycle

    def start(self) -> None:
        if not self.config.enabled:
            logger.info("Auditor disabled (AUDITOR_ENABLED=0)")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_requested.clear()
        self._thread = threading.Thread(
            target=self._scheduler_loop,
            name="auditor-scheduler",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Auditor service started (daily @ %dh PT, trade trigger %d, pnl trigger %.1f%%)",
            self.config.daily_run_hour_pacific,
            self.config.trade_count_trigger,
            self.config.pnl_pct_trigger * 100.0,
        )

    def stop(self) -> None:
        if not self._thread:
            return
        self._stop_requested.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=5)
            if thread.is_alive():
                logger.warning(
                    "Auditor scheduler did not stop within 5s; it is a daemon and "
                    "will be terminated when the process exits."
                )
        self._thread = None
        logger.info("Auditor service stopped")

    # --------------------------------------------------------------------- public commands

    def run_audit(self, *, trigger: str = "manual") -> AuditReport:
        """Run a full audit synchronously and return the report."""
        with self._lock:
            return self._run_audit_locked(trigger=trigger)

    def confirm_proposal(self, proposal_id: str) -> str:
        arg = (proposal_id or "").strip()
        if not arg:
            return "Provide a proposal ID — see `Auditor -pending` (alias `-list`)."
        if arg.lower() == "all":
            with self._lock:
                self.state.prune_expired()
                ids = list(self.state.pending_proposals.keys())
            return self._confirm_batch(ids)
        if "," in arg:
            ids = [part.strip() for part in arg.split(",") if part.strip()]
            return self._confirm_batch(ids)
        return self._confirm_single(arg)

    def _confirm_single(self, proposal_id: str) -> str:
        with self._lock:
            proposal, err = self._apply_proposal_locked(proposal_id)
            if err:
                return err
            self.state.prune_expired()
            self._save_state()

        restart_scheduled = False
        if self.config.confirm_restart_enabled and self._request_restart is not None:
            try:
                self._request_restart(
                    f"auditor-confirm {proposal_id} applied "
                    f"{proposal.knob}={proposal.proposed_value}"
                )
                restart_scheduled = True
            except Exception:  # noqa: BLE001
                logger.exception("Confirm restart request failed")

        return self._format_confirm_success(proposal, restart_scheduled)

    def _confirm_batch(self, proposal_ids: list[str]) -> str:
        if not proposal_ids:
            return "No pending proposals to confirm — run `Auditor -review` first."

        with self._lock:
            self.state.prune_expired()
            to_apply: list = []
            for pid in proposal_ids:
                proposal = self.state.get_proposal(pid)
                if proposal is None:
                    return (
                        f"No pending proposal `{pid}`. "
                        "Use `Auditor -pending` to list valid IDs."
                    )
                if self.state.is_expired(proposal):
                    self.state.consume_proposal(pid)
                    return (
                        f"Proposal `{pid}` expired at {proposal.expires_at}. "
                        "Run `Auditor -review` for fresh suggestions."
                    )
                to_apply.append(proposal)

            dup_knobs = knobs_with_conflicts(to_apply)
            if dup_knobs:
                rendered = ", ".join(f"`{k}`" for k in dup_knobs)
                return (
                    f"Refused batch confirm — duplicate knobs: {rendered}. "
                    "Pick one proposal per knob, then retry."
                )

            applied: list = []
            errors: list[str] = []
            for proposal in to_apply:
                try:
                    apply_proposal(proposal, self.overrides_file)
                except ValueError as exc:
                    errors.append(f"`{proposal.id}` ({proposal.knob}): {exc}")
                    continue
                self.state.consume_proposal(proposal.id)
                applied.append(proposal)

            self.state.prune_expired()
            self._save_state()

        if not applied:
            return "No proposals applied.\n" + "\n".join(errors)

        restart_scheduled = False
        if self.config.confirm_restart_enabled and self._request_restart is not None:
            try:
                summary = ", ".join(f"{p.knob}={p.proposed_value}" for p in applied)
                self._request_restart(f"auditor batch-confirm applied {summary}")
                restart_scheduled = True
            except Exception:  # noqa: BLE001
                logger.exception("Batch confirm restart request failed")

        lines = [
            f"Applied **{len(applied)}** proposal(s):",
        ]
        for p in applied:
            lines.append(
                f"• `{p.knob}` = `{p.proposed_value}` (was `{p.current_value}`, id `{p.id}`)"
            )
        if errors:
            lines.append("")
            lines.append("Skipped:")
            lines.extend(f"• {e}" for e in errors)
        if restart_scheduled:
            lines.append(
                "\n:arrows_counterclockwise: **Restarting bot to load new settings…**"
            )
        else:
            lines.append(
                "\n:warning: **Restart `main.py`** for overrides to take effect."
            )
        return "\n".join(lines)

    def _apply_proposal_locked(self, proposal_id: str):
        """Validate + apply one proposal under ``self._lock``. Returns (proposal, error)."""
        proposal = self.state.get_proposal(proposal_id)
        if proposal is None:
            self.state.prune_expired()
            return None, (
                f"No pending proposal `{proposal_id}`. Use `Auditor -pending` to list."
            )
        if self.state.is_expired(proposal):
            self.state.consume_proposal(proposal_id)
            return None, (
                f"Proposal `{proposal_id}` expired at {proposal.expires_at}. "
                "Run `Auditor -review` for a fresh suggestion."
            )
        try:
            apply_proposal(proposal, self.overrides_file)
        except ValueError as exc:
            return None, f"Refused to apply `{proposal.knob}`: {exc}"
        self.state.consume_proposal(proposal_id)
        return proposal, None

    def _format_confirm_success(self, proposal, restart_scheduled: bool) -> str:
        if restart_scheduled:
            return (
                f"Applied `{proposal.knob}` = `{proposal.proposed_value}` "
                f"(was `{proposal.current_value}`). "
                f"Override stored in `runtime_overrides.json`.\n"
                f":arrows_counterclockwise: **Restarting bot to load new settings…** "
                f"The process will shut down cleanly and come back with the updated value.\n"
                f"Use `Auditor -revert {proposal.knob}` after restart if you change your mind."
            )
        return (
            f"Applied `{proposal.knob}` = `{proposal.proposed_value}` "
            f"(was `{proposal.current_value}`). "
            f"Override stored in `runtime_overrides.json`.\n"
            f":warning: **A full process restart is required for the new value to "
            f"take effect.** Quit the running `main.py` (Ctrl+C in its terminal) and "
            f"launch it again. The `stop` / `start` Discord commands only pause "
            f"trading — they do **not** reload settings.\n"
            f"Use `Auditor -revert {proposal.knob}` to undo before restart, or "
            f"`Auditor -pending` to verify."
        )

    def list_pending(self) -> str:
        with self._lock:
            self.state.prune_expired()
            self._save_state()
            proposals = list(self.state.pending_proposals.values())
            overrides = list_overrides(self.overrides_file)

        lines: list[str] = []
        if proposals:
            conflicts = knobs_with_conflicts(proposals)
            if len(proposals) > 3:
                note = f"⚠ **{len(proposals)} proposals pending** — review before confirming."
                if conflicts:
                    note += f" Conflicting knobs: {', '.join(f'`{k}`' for k in conflicts)}."
                lines.append(note)
                lines.append("")
            lines.append("**Pending auditor proposals:**")
            for p in proposals:
                lines.append(
                    f"• `{p.id}` `{p.knob}` {p.current_value} → {p.proposed_value} "
                    f"({p.severity}) — expires {p.expires_at}\n  _{p.rationale}_"
                )
            lines.append("")
            lines.append(
                "Apply with `Auditor -confirm <id>`, `Auditor -confirm all`, "
                "or `Auditor -confirm id1,id2` before the TTL."
            )
        else:
            lines.append("No pending proposals — run `Auditor -review` to generate fresh suggestions.")

        if overrides:
            lines.append("")
            lines.append("**Active runtime overrides:**")
            for knob, value in sorted(overrides.items()):
                lines.append(f"• `{knob}` = `{value}` (revert: `Auditor -revert {knob}`)")
        return "\n".join(lines)

    def revert(self, knob: str) -> str:
        knob = (knob or "").strip().upper()
        if not knob:
            return "Provide a knob name — see `Auditor -pending` for the active list."
        if knob not in ALLOWED_KNOBS:
            return f"`{knob}` is not an auditor-managed knob. Allowed: {', '.join(ALLOWED_KNOBS)}."
        with self._lock:
            removed = revert_override(knob, self.overrides_file)
        if not removed:
            return f"`{knob}` had no active override."
        return (
            f"Reverted `{knob}`. Restart the bot for the original `.env` value to take effect."
        )

    def create_proposal(
        self,
        knob: str,
        proposed_value,
        rationale: str = "",
        severity: str = "medium",
    ) -> dict:
        """Register a PENDING proposal into the same store as audit proposals.

        Used by the conversational chat so the Auditor can answer "make a
        proposal to improve strategy" with a concrete, confirmable suggestion.

        CRITICAL: this only *creates* a pending proposal — it never applies the
        change. The user must still run ``Auditor -confirm <id>`` (which writes
        ``runtime_overrides.json``). All existing auto-apply guardrails are
        untouched. Returns a JSON-serialisable dict (``error`` key on failure).
        """
        knob_norm = (knob or "").strip().upper()
        if knob_norm not in ALLOWED_KNOBS:
            return {
                "error": (
                    f"`{knob}` is not an auditor-tunable knob. "
                    f"Choose one of: {', '.join(ALLOWED_KNOBS)}."
                )
            }
        try:
            proposed = float(proposed_value)
        except (TypeError, ValueError):
            return {"error": f"proposed_value must be numeric, got {proposed_value!r}."}

        field = KNOB_TO_FIELD.get(knob_norm)
        current = float(getattr(self.settings, field, 0.0)) if field else 0.0
        rationale = (rationale or "").strip() or "Proposed via Auditor chat."
        try:
            proposal = build_proposal(
                knob_norm,
                current,
                proposed,
                rationale,
                severity=severity,
                ttl_minutes=self.config.proposals_ttl_minutes,
            )
        except ValueError as exc:
            return {"error": str(exc)}

        with self._lock:
            self.state.add_proposal(proposal)
            self.state.prune_expired()
            self._save_state()

        logger.warning(
            "Auditor chat created pending proposal %s (%s: %s -> %s, severity=%s)",
            proposal.id, proposal.knob, proposal.current_value,
            proposal.proposed_value, proposal.severity,
        )
        return {
            "created": True,
            "id": proposal.id,
            "knob": proposal.knob,
            "current_value": proposal.current_value,
            "proposed_value": proposal.proposed_value,
            "severity": proposal.severity,
            "rationale": proposal.rationale,
            "expires_at": proposal.expires_at,
            "confirm_hint": (
                f"Pending proposal `{proposal.id}` created. The user can review it "
                f"with `Auditor -list` and apply it with `Auditor -confirm {proposal.id}`. "
                "It is NOT applied automatically."
            ),
        }

    # ---------------------------------------------------------- chat surface

    def ask(self, question: str) -> str:
        """Single-turn Q&A. No history retained."""
        chat = self._get_chat_service()
        if isinstance(chat, str):
            return chat  # init error string
        result = chat.ask(question)
        return self._format_chat_reply(result)

    def chat(self, session_id: str, message: str) -> str:
        """Multi-turn chat. History keyed by ``session_id`` (typically the user id)."""
        chat = self._get_chat_service()
        if isinstance(chat, str):
            return chat
        result = chat.chat(session_id, message)
        return self._format_chat_reply(result)

    def clear_chat(self, session_id: str) -> str:
        """Wipe the chat history for one session (the calling user)."""
        if self._chat is None:
            return "Chat history was already empty."
        cleared = self._chat.clear(session_id)
        return f"Cleared {cleared} message(s) from your Auditor chat history."

    def chat_status(self) -> str:
        """Backend + model + per-session turn counts."""
        if not self.config.chat_enabled:
            return (
                "**Auditor chat:** disabled.\n"
                "Set `AUDITOR_CHAT_ENABLED=1` and `GEMINI_API_KEY=...` in `.env`, then restart."
            )
        chat = self._get_chat_service()
        if isinstance(chat, str):
            return f"**Auditor chat:** init error.\n{chat}"
        lines = [
            "**Auditor chat:** enabled",
            f"• Backend: `{self.config.chat_backend}` model `{self.config.chat_model}`",
            f"• Max turns retained per session: {self.config.chat_max_turns}",
            f"• Max tool round-trips per question: {self.config.chat_tool_iterations}",
            f"• Tool result truncation: {self.config.chat_tool_result_max_chars} chars",
            f"• Reply token cap: {self.config.chat_max_tokens}",
        ]
        summary = chat.history_summary()
        if summary:
            lines.append("• Active sessions:")
            for sid, turns in sorted(summary.items()):
                lines.append(f"   - `{sid}`: {turns} turn(s)")
        else:
            lines.append("• Active sessions: none")
        return "\n".join(lines)

    def _format_chat_reply(self, result) -> str:
        text = result.text or "(no reply)"
        # Discord caps at 2000 chars; leave headroom for the truncation marker.
        if len(text) > 1900:
            text = text[:1880] + "\n…(reply truncated)"
        return text

    def _get_chat_service(self):
        """Return a ready ChatService, or an error-string explaining why not."""
        if not self.config.chat_enabled:
            return (
                "Auditor chat is disabled. Set `AUDITOR_CHAT_ENABLED=1` and "
                "`GEMINI_API_KEY=...` in `.env`, then restart."
            )
        if self._chat is not None:
            return self._chat
        if self._chat_init_error:
            return self._chat_init_error
        try:
            self._chat = self._build_chat_service()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to build ChatService")
            self._chat_init_error = (
                f"Failed to initialise chat backend: {exc}.\n"
                "Check `AUDITOR_CHAT_BACKEND`, `AUDITOR_CHAT_MODEL`, and the "
                "API key, then restart."
            )
            return self._chat_init_error
        return self._chat

    def _build_chat_service(self):
        """Wire up ToolRegistry + Backend + ChatService."""
        from bot.auditor.chat import (
            ChatService,
            GeminiBackend,
            NullBackend,
            build_tool_registry,
        )

        backend_name = (self.config.chat_backend or "gemini").lower()
        if backend_name == "null":
            backend = NullBackend()
        elif backend_name == "gemini":
            backend = GeminiBackend(api_key=self.config.chat_api_key, model=self.config.chat_model)
            if not backend.available:
                return (
                    "Gemini chat needs `GEMINI_API_KEY` set in `.env` (get a free key at "
                    "https://aistudio.google.com), then restart."
                )
        else:
            return (
                f"Unknown chat backend `{backend_name}`. Use `gemini` (or `null` for tests)."
            )

        tools = build_tool_registry(
            broker=self.broker,
            settings=self.settings,
            portfolio_log=self.portfolio_log,
            overrides_file=self.overrides_file,
            audit_state_provider=lambda: self.state,
            watchdog_state_provider=self.watchdog_state_provider,
            news_client_provider=lambda: self._news_client_for_chat(),
            reports_dir=self.config.reports_dir,
            proposal_creator=self.create_proposal,
        )
        return ChatService(
            backend=backend,
            tools=tools,
            max_turns=self.config.chat_max_turns,
            max_tool_iterations=self.config.chat_tool_iterations,
            temperature=self.config.chat_temperature,
            max_output_tokens=self.config.chat_max_tokens,
            tool_result_max_chars=self.config.chat_tool_result_max_chars,
        )

    def _news_client_for_chat(self):
        """Return the same NewsClient used by audits, building lazily if needed."""
        if self._news_client is not None:
            return self._news_client
        if not self.config.news_enabled:
            return None
        try:
            from bot.auditor.news_client import parse_rss_feed_env

            self._news_client = NewsClient(
                providers=self.config.news_provider,
                rss_feeds=parse_rss_feed_env(self.config.rss_feeds),
                api_key=self.config.cryptopanic_api_key,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to build news client for chat")
            return None
        return self._news_client

    def status(self) -> str:
        with self._lock:
            self.state.prune_expired()
            self._save_state()
            pending = len(self.state.pending_proposals)
            last_sched = self.state.last_scheduled_run_at or "never"
            last_event = self.state.last_event_run_at or "never"
        overrides = list_overrides(self.overrides_file)
        thread_alive = bool(self._thread and self._thread.is_alive())
        lines = [
            f"**Auditor** — enabled={self.config.enabled}, thread={'alive' if thread_alive else 'stopped'}",
            f"• Daily run hour (Pacific): {self.config.daily_run_hour_pacific}",
            f"• Trade-count trigger: {self.config.trade_count_trigger}",
            f"• PnL trigger: {self.config.pnl_pct_trigger:.2%}",
            f"• News providers: {self.config.news_provider} (enabled={self.config.news_enabled})",
            f"• Last scheduled run: {last_sched}",
            f"• Last event run: {last_event}",
            f"• Pending proposals: {pending}",
            f"• Active overrides: {len(overrides)}",
        ]
        if overrides:
            lines.append("  " + ", ".join(f"`{k}`={v}" for k, v in sorted(overrides.items())))
        # Sleep-window auto-apply status
        if self.config.autoapply_enabled:
            lines.append(
                f"• Auto-apply window: {self.config.autoapply_window_start_hour:02d}:00–"
                f"{self.config.autoapply_window_end_hour:02d}:00 PT "
                f"(min severity `{self.config.autoapply_min_severity}`, "
                f"cap {self.config.autoapply_max_per_night}/night, "
                f"restart={'on' if self.config.autoapply_restart_enabled else 'off'})"
            )
            if self.state.last_auto_apply_at:
                lines.append(
                    f"• Last auto-apply: `{self.state.last_auto_apply_knob}`="
                    f"`{self.state.last_auto_apply_value}` at {self.state.last_auto_apply_at} "
                    f"(night {self.state.last_auto_apply_night_key}, count={self.state.auto_applies_this_night})"
                )
        else:
            lines.append("• Auto-apply: disabled")
        return "\n".join(lines)

    def help_text(self) -> str:
        # The canonical help text lives in `bot.discord_bot.AuditorHelpText`
        # — re-exported below for tests that import this module directly.
        return AuditorHelpText

    # --------------------------------------------------------------------- trade events

    def note_trade(self, trade: dict) -> None:
        """Called by the engine after each executed trade.

        Triggers an event-driven audit when either:
        - cumulative trade count since last event run >= trade_count_trigger
        - cumulative net pnl since last event run crosses pnl_pct_trigger of portfolio
        """
        if not self.config.enabled:
            return
        try:
            self._maybe_event_run(trade)
        except Exception:  # noqa: BLE001 — never crash the engine
            logger.exception("Auditor note_trade failed")

    # --------------------------------------------------------------------- internals

    def _scheduler_loop(self) -> None:
        while not self._stop_requested.is_set():
            try:
                self._maybe_scheduled_run()
            except Exception:  # noqa: BLE001
                logger.exception("Auditor scheduler tick failed")
            self._stop_requested.wait(self.SCHEDULER_TICK_SECONDS)

    def _scheduled_day_from_state(self) -> str | None:
        """Pacific YYYY-MM-DD extracted from persisted last_scheduled_run_at."""
        last = self.state.last_scheduled_run_at
        if not last:
            return None
        return last[:10] if len(last) >= 10 else None

    def _scheduled_already_ran_today(self, today: str) -> bool:
        last_day = self._scheduled_day_from_state()
        return bool(today and last_day == today)

    def _discord_worthy_in_quiet(self, proposals: list | None, insights) -> bool:
        """Whether a quiet-mode audit should still post to Discord."""
        if bool(getattr(insights, "over_concentrated", None)):
            return True
        for proposal in proposals or []:
            severity = getattr(proposal, "severity", "low")
            if self.SEVERITY_RANK.get(severity, 0) >= self.SEVERITY_RANK["medium"]:
                return True
        return False

    def _maybe_scheduled_run(self) -> None:
        now = self._clock()
        today = now.strftime("%Y-%m-%d") if hasattr(now, "strftime") else ""
        if self._last_scheduled_day == today:
            return
        if self._scheduled_already_ran_today(today):
            self._last_scheduled_day = today
            return
        if hasattr(now, "hour") and now.hour < self.config.daily_run_hour_pacific:
            return
        logger.info("Auditor — running scheduled audit for %s", today)
        with self._lock:
            self._run_audit_locked(trigger="scheduled")
            self.state.mark_scheduled_run()
            self._save_state()
        self._last_scheduled_day = today

    def _maybe_event_run(self, trade: dict) -> None:
        current_count = self._current_trade_count()
        trades_since = max(0, current_count - self.state.last_trade_count_at_event)
        gain_since = float(trade.get("gain_loss", 0.0))
        portfolio = self._current_portfolio_value()
        pnl_crossed = False
        if portfolio > 0 and abs(gain_since) / portfolio >= self.config.pnl_pct_trigger:
            pnl_crossed = True

        count_crossed = trades_since >= max(1, self.config.trade_count_trigger)
        if not (count_crossed or pnl_crossed):
            return
        reason = "trade_count" if count_crossed else "pnl_threshold"
        logger.info(
            "Auditor — event-triggered audit (%s; trades_since=%d, last_gain=%.2f, portfolio=%.2f)",
            reason, trades_since, gain_since, portfolio,
        )
        with self._lock:
            self._run_audit_locked(trigger=f"event:{reason}")
            self.state.mark_event_run(trade_count=current_count, pnl=portfolio)
            self._save_state()

    def _run_audit_locked(self, *, trigger: str) -> AuditReport:
        started_at = format_pacific()
        trades, holdings, usd_prices = self._snapshot_inputs()

        insights = analyze_trades(
            trades,
            holdings,
            self.settings,
            usd_prices=usd_prices,
        )

        live_broker = self._resolve_live_broker()
        live_snapshot = load_live_audit_snapshot(
            self.settings,
            live_broker=live_broker,
            portfolio_log=self.portfolio_log,
        )
        live_insights = None
        if live_snapshot is not None and live_snapshot.trades:
            live_insights = analyze_trades(
                live_snapshot.trades,
                live_snapshot.holdings,
                self.settings,
                usd_prices=usd_prices,
            )
        goal_view = build_audit_goal_view(
            self.settings,
            live_snapshot=live_snapshot,
            portfolio_log=self.portfolio_log,
        )

        forecast = forecast_pnl(insights, trades)

        headlines = []
        if self.config.news_enabled:
            if self._news_client is None:
                from bot.auditor.news_client import parse_rss_feed_env

                self._news_client = NewsClient(
                    providers=self.config.news_provider,
                    rss_feeds=parse_rss_feed_env(self.config.rss_feeds),
                    api_key=self.config.cryptopanic_api_key,
                )
            client = self._news_client
            tracked_assets = list({
                str(t.get("from_asset", ""))
                for t in trades
                if t.get("from_asset")
            } | {
                str(t.get("to_asset", ""))
                for t in trades
                if t.get("to_asset")
            } | set(holdings.keys()))
            tracked_assets = [a for a in tracked_assets if a and a != "USD"]
            headlines = client.fetch_headlines(tracked_assets, self.config.news_max_items)

        proposals = propose_changes(
            insights,
            forecast,
            self.settings,
            ttl_minutes=self.config.proposals_ttl_minutes,
        )

        markdown_path = self._write_markdown(
            insights,
            forecast,
            headlines,
            proposals,
            trigger=trigger,
            live_snapshot=live_snapshot,
            live_insights=live_insights,
            goal_view=goal_view,
        )
        summary = render_discord_summary(
            insights, forecast, headlines, proposals,
            markdown_path=markdown_path,
            trigger=trigger,
            live_snapshot=live_snapshot,
            live_insights=live_insights,
            goal_view=goal_view,
            live_enabled=bool(getattr(self.settings, "live_enabled", False)),
        )

        for proposal in proposals:
            self.state.add_proposal(proposal, replace_same_knob=True)
        self.state.prune_expired()
        self._save_state()

        self._post_summary_to_discord(
            summary,
            trigger=trigger,
            proposals=proposals,
            insights=insights,
            markdown_path=markdown_path,
        )

        # Sleep-window auto-apply happens AFTER the regular summary post so the
        # user wakes up to two messages in chronological order: the audit
        # summary, then the auto-apply notice. Failures here never propagate.
        try:
            self._maybe_auto_apply(proposals)
        except Exception:  # noqa: BLE001 — must never crash the audit thread
            logger.exception("Auto-apply check failed")

        return AuditReport(
            trigger=trigger,
            started_at=started_at,
            markdown_path=markdown_path,
            summary=summary,
            insights=insights,
            forecast=forecast,
            headlines=headlines,
            proposals=proposals,
        )

    # ----------------------------------------------------- sleep-window auto-apply

    def _maybe_auto_apply(self, proposals: list) -> None:
        """Apply ONE eligible proposal during the configured sleep window.

        All gates must pass:
          1. ``autoapply_enabled`` is True.
          2. Current Pacific hour is within ``[start_hour, end_hour)``.
          3. ``autoapply_max_per_night`` not yet reached for this night key.
          4. Broker is healthy (no drawdown hibernation, no paused state).
          5. At least one proposal has severity >= ``autoapply_min_severity``.

        On success the proposal is consumed, ``runtime_overrides.json`` is
        written, state is saved, and (if ``autoapply_restart_enabled``) a
        process restart is requested.
        """
        if not self.config.autoapply_enabled:
            return
        if not proposals:
            return

        with self._lock:
            pending = list(self.state.pending_proposals.values())
        if knobs_with_conflicts(pending):
            logger.info(
                "Auto-apply: skipping — pending store has conflicting knobs: %s",
                ", ".join(knobs_with_conflicts(pending)),
            )
            return

        now = self._clock()
        if not hasattr(now, "hour"):
            return  # non-datetime clock (shouldn't happen in production)

        in_window, night_key = self._inside_sleep_window(now)
        if not in_window:
            return

        # Already at the per-night cap?
        if (
            self.state.last_auto_apply_night_key == night_key
            and self.state.auto_applies_this_night >= max(1, self.config.autoapply_max_per_night)
        ):
            logger.info(
                "Auto-apply: per-night cap reached (%d/%d) for %s — skipping",
                self.state.auto_applies_this_night,
                self.config.autoapply_max_per_night,
                night_key,
            )
            return

        # Safety: never tune a hibernating bot. If risk has paused us or the
        # broker is in a re-eval state, surface the suggestion but don't apply.
        if not self._broker_is_healthy():
            logger.info("Auto-apply: broker not healthy (drawdown/paused) — skipping")
            return

        # Never auto-apply when the current audit batch still has duplicate knobs.
        if knobs_with_conflicts(proposals):
            logger.info(
                "Auto-apply: skipping — conflicting knobs in audit batch: %s",
                ", ".join(knobs_with_conflicts(proposals)),
            )
            return

        min_rank = self.SEVERITY_RANK.get(self.config.autoapply_min_severity.lower(), 2)
        eligible = [
            p for p in proposals
            if self.SEVERITY_RANK.get(getattr(p, "severity", "low"), 0) >= min_rank
        ]
        if not eligible:
            logger.info(
                "Auto-apply: no proposal meets min severity %r",
                self.config.autoapply_min_severity,
            )
            return

        # Pick the highest-severity proposal; tiebreak by knob alphabetical for determinism.
        eligible.sort(
            key=lambda p: (-self.SEVERITY_RANK.get(p.severity, 0), p.knob),
        )
        chosen = eligible[0]

        # Apply + record. Errors propagate up to the outer try/except in the caller.
        try:
            apply_proposal(chosen, self.overrides_file)
        except ValueError as exc:
            logger.warning("Auto-apply refused %s: %s", chosen.knob, exc)
            return

        self.state.consume_proposal(chosen.id)
        self.state.mark_auto_apply(
            proposal_id=chosen.id,
            knob=chosen.knob,
            value=chosen.proposed_value,
            night_key=night_key,
        )
        self.state.prune_expired()
        self._save_state()

        logger.warning(
            "Auto-applied %s = %s (was %s) during sleep window (night=%s, severity=%s)",
            chosen.knob, chosen.proposed_value, chosen.current_value,
            night_key, chosen.severity,
        )

        self._notify_auto_apply(chosen, night_key)

        if self.config.autoapply_restart_enabled and self._request_restart is not None:
            try:
                self._request_restart(
                    f"auditor auto-applied {chosen.knob}={chosen.proposed_value} at "
                    f"{self.state.last_auto_apply_at}"
                )
            except Exception:  # noqa: BLE001
                logger.exception("Auto-apply restart request failed")

    def _inside_sleep_window(self, now) -> tuple[bool, str]:
        """Return ``(inside, night_key)`` for the configured window.

        ``night_key`` is the ``YYYY-MM-DD`` date of the night the window
        opened. For a simple same-day window like 1am-7am, this is just
        today's date. For a cross-midnight window like 23:00-07:00 we anchor
        on the *evening* date so the same night is one logical unit.
        """
        start = max(0, min(23, self.config.autoapply_window_start_hour))
        end = max(0, min(24, self.config.autoapply_window_end_hour))
        if start == end:
            return False, ""
        hour = now.hour
        today_key = now.strftime("%Y-%m-%d") if hasattr(now, "strftime") else ""
        if start < end:
            inside = start <= hour < end
            return inside, today_key
        # Cross-midnight window: e.g. start=23, end=7 means [23, 24) ∪ [0, 7).
        if hour >= start:
            return True, today_key
        if hour < end:
            # Belongs to the previous evening; anchor on yesterday's date.
            try:
                from datetime import timedelta as _td
                yesterday = (now - _td(days=1)).strftime("%Y-%m-%d")
            except Exception:  # noqa: BLE001 — fall back to today's key on any clock issue
                yesterday = today_key
            return True, yesterday
        return False, today_key

    def _broker_is_healthy(self) -> bool:
        """True when it's safe to auto-tune. False during drawdown/hibernation."""
        try:
            risk = getattr(self.broker, "risk", None)
            if risk is None:
                return True  # no risk subsystem — caller decides
            risk_state = getattr(risk, "state", None)
            if risk_state is None:
                return True
            if getattr(risk_state, "paused_until", None):
                return False
            if getattr(risk_state, "hibernate_alert_sent", False):
                # `hibernate_alert_sent` only flips True while hibernation is in
                # effect; the trader clears it when re-evaluation resolves.
                return False
        except Exception:  # noqa: BLE001
            logger.exception("Health check failed; treating broker as unhealthy")
            return False
        return True

    def _notify_auto_apply(self, proposal, night_key: str) -> None:
        """Post a loud Discord message describing what just happened."""
        if not self.discord:
            return
        try:
            if hasattr(self.discord, "config") and not getattr(self.discord.config, "enabled", False):
                return
            message = (
                f":robot: **Auditor auto-applied during sleep window** ({night_key})\n"
                f"• Knob: `{proposal.knob}`\n"
                f"• Was: `{proposal.current_value}` → Now: `{proposal.proposed_value}`\n"
                f"• Severity: `{proposal.severity}` (id `{proposal.id}`)\n"
                f"• Rationale: {proposal.rationale}\n"
                f"• Applied at: {self.state.last_auto_apply_at}\n"
                + (
                    "• Bot is restarting now to load the new value.\n"
                    if (self.config.autoapply_restart_enabled and self._request_restart is not None)
                    else "• Auto-restart disabled — restart `main.py` manually for the new value to take effect.\n"
                )
                + f"• Disagree? Run `Auditor -revert {proposal.knob}` after restart."
            )
            # Pin so it stays visible when the user wakes up.
            poster = getattr(self.discord, "post_important", None)
            if callable(poster):
                poster(message, pin=True, source="Auditor")
            else:  # extremely defensive fallback for stubs/tests
                fallback = getattr(self.discord, "post_plain", None)
                if callable(fallback):
                    fallback(message, pin=True, source="Auditor")
        except Exception:  # noqa: BLE001
            logger.exception("Failed to post auto-apply Discord notice")

    def _write_markdown(
        self,
        insights,
        forecast,
        headlines,
        proposals,
        *,
        trigger: str,
        live_snapshot=None,
        live_insights=None,
        goal_view=None,
    ) -> Path | None:
        try:
            now = self._clock()
            day_dir = self.config.reports_dir / now.strftime("%Y-%m-%d")
            day_dir.mkdir(parents=True, exist_ok=True)
            filename = f"audit-{now.strftime('%H%M%S')}.md"
            target = day_dir / filename
            body = render_markdown_report(
                insights, forecast, headlines, proposals,
                settings=self.settings,
                trigger=trigger,
                live_snapshot=live_snapshot,
                live_insights=live_insights,
                goal_view=goal_view,
            )
            target.write_text(body, encoding="utf-8")
            return target
        except OSError as exc:
            logger.warning("Auditor could not write markdown report: %s", exc)
            return None

    def _post_summary_to_discord(
        self,
        summary: str,
        *,
        trigger: str = "manual",
        proposals: list | None = None,
        insights=None,
        markdown_path: Path | None = None,
    ) -> None:
        if not self.discord:
            return
        if self.config.discord_quiet and trigger.startswith(("scheduled", "event:")):
            if not self._discord_worthy_in_quiet(proposals, insights):
                logger.info(
                    "Auditor quiet mode — skipping Discord for %s (no medium+ proposals/issues)",
                    trigger,
                )
                return
        try:
            if hasattr(self.discord, "config") and not getattr(self.discord.config, "enabled", False):
                return
            text = summary[:DISCORD_MAX_LEN] if len(summary) > DISCORD_MAX_LEN else summary
            attachment = None
            attach_name = ""
            truncate_note = None
            if markdown_path is not None and markdown_path.exists():
                try:
                    attachment, attach_name, truncate_note = prepare_report_attachment(markdown_path)
                except OSError as exc:
                    logger.warning("Auditor could not read report for attachment: %s", exc)
            if truncate_note:
                text = f"{text}\n_{truncate_note}_"
            poster = getattr(self.discord, "post_with_attachment", None)
            if attachment and callable(poster):
                poster(text, attachment, attach_name, pin=False, source="Auditor")
            else:
                self.discord.post_important(text, pin=False, source="Auditor")
        except Exception:  # noqa: BLE001
            logger.exception("Auditor failed to post summary to Discord")

    def _resolve_live_broker(self):
        if self._live_broker_provider is None:
            return None
        try:
            return self._live_broker_provider()
        except Exception:  # noqa: BLE001
            logger.exception("Live broker provider failed")
            return None

    def _snapshot_inputs(self) -> tuple[list[dict], dict[str, float], dict[str, float] | None]:
        trades: list[dict] = []
        holdings: dict[str, float] = {}
        usd_prices: dict[str, float] | None = None
        if self.broker is not None:
            try:
                trades = list(self.broker.state.trades)
                holdings = dict(self.broker.state.balances)
            except AttributeError:
                pass
        if self.portfolio_log is not None:
            try:
                snap = self.portfolio_log.load()
            except Exception:  # noqa: BLE001
                snap = None
            if snap is not None:
                prices: dict[str, float] = {}
                for asset, row in snap.holdings.items():
                    price = float(row.get("usd_price", 0.0))
                    if price > 0:
                        prices[asset] = price
                if prices:
                    usd_prices = prices
        return trades, holdings, usd_prices

    def _current_trade_count(self) -> int:
        if self.broker is None:
            return 0
        try:
            return len(self.broker.state.trades)
        except AttributeError:
            return 0

    def _current_portfolio_value(self) -> float:
        if self.portfolio_log is not None:
            try:
                snap = self.portfolio_log.load()
            except Exception:  # noqa: BLE001
                snap = None
            if snap is not None and snap.portfolio_usd > 0:
                return float(snap.portfolio_usd)
        if self.broker is not None:
            try:
                return float(self.broker.risk.peak_portfolio or 0.0)
            except AttributeError:
                return 0.0
        return 0.0

    def _save_state(self) -> None:
        try:
            self.state.save(self.config.state_file)
        except OSError as exc:
            logger.warning("Auditor could not persist state: %s", exc)


AuditorHelpText = """**Auditor commands** (read-only review + tier-2 proposals):
• `Auditor -review` — run a full audit (posts summary + .txt report attachment)
• `Auditor -forecast` — same as review but reply highlights forecast bands
• `Auditor -strategy <name>` — review focused on the strategies you list
• `Auditor -summary` — last-summary recall (re-runs if none)
• `Auditor -pending` / `-list` — list pending proposals + active overrides
• `Auditor -confirm <id>` — apply one proposal (writes `runtime_overrides.json`)
• `Auditor -confirm all` or `-confirm id1,id2` — batch apply (one per knob max)
• `Auditor -revert <knob>` — remove an active override
• `Auditor -help` — this message

All proposals expire (default 60 min). The auditor never edits `.env`.
Kraken Trade Prop ($5k eval) is **not** supported — see `docs/kraken-prop.md`."""
