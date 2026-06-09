import logging
import os
import sys
import time

from datetime import datetime
from pathlib import Path

from bot.alerts import AlertConfig, AlertManager
from bot.auditor.config import AuditorConfig
from bot.auditor_service import AuditorService
from bot.circuit_breaker import CircuitBreaker
from bot.data import KrakenData
from bot.discord_bot import (
    AuditorHelpText,
    DiscordBot,
    DiscordConfig,
    HelpText,
    TradeBotHelpText,
    WatchDogHelpText,
)
from bot.display import TerminalDisplay
from bot.fee_engine import FeeEngine
from bot.local_time import format_pacific
from bot.markets import MarketRegistry
from bot.paper_broker import PaperBroker
from bot.paper_portfolio import PaperPortfolioLog
from bot.portfolio_constraints import PortfolioConstraints
from bot.preflight import PreFlightValidator
from bot.strategy_governor import StrategyGovernor
from bot.report import (
    format_trade_executed_alert,
    format_planned_actions,
    format_pnl_milestone_alert,
    format_portfolio_summary,
    format_strategy_status,
    pnl_milestone_band,
)
from bot.risk import HibernateEvent, RiskManager
from bot.runtime import BotRuntime, TickSnapshot
from bot.status import build_status_snapshot
from bot.strategies.base import Strategy, StrategyContext
from bot.trade_log import BotFileLogger, ReceiptWriter
from bot.watchdog_service import WatchdogService
from config import ROOT, Settings



logger = logging.getLogger(__name__)





class TradingEngine:

    def __init__(self, settings: Settings, strategy: Strategy):

        self.settings = settings

        self.strategy = strategy

        self.runtime = BotRuntime()

        self.data = KrakenData(settings)

        self.markets = MarketRegistry(self.data.exchange, settings.watch_assets)

        self.display = TerminalDisplay()

        self.file_log = BotFileLogger(settings.log_dir, settings.log_rotate_hours)

        self.receipts = ReceiptWriter(settings.receipts_dir)

        self.portfolio_log = PaperPortfolioLog(settings.paper_portfolio_file)

        self.broker = PaperBroker(

            initial_balances=settings.initial_balances,

            fee_rate=settings.fee_rate,

            state_file=settings.state_file,

            min_usd_trade=settings.min_usd_trade,

            reset=settings.reset_paper_state,

        )

        self.risk = RiskManager(

            risk_state=self.broker.risk,

            fee_rate=settings.fee_rate,

            drawdown_hibernate_pct=settings.drawdown_hibernate_pct,

            hibernate_hours=settings.hibernate_hours,

            trade_cooldown_seconds=settings.trade_cooldown_seconds,

            max_trades_per_hour=settings.max_trades_per_hour,

            min_trade_edge=settings.min_trade_edge,

            leader_stable_seconds=settings.leader_stable_seconds,

            fee_safety_multiplier=settings.fee_safety_multiplier,

            idle_reeval_hours=settings.idle_reeval_hours,

            idle_reeval_max_attempts=settings.idle_reeval_max_attempts,

            min_net_profit_pct=settings.min_net_profit_pct,

            stat_arb_zscore_threshold=settings.stat_arb_zscore_threshold,

            save_callback=self.broker.save,

        )

        self.fee_engine = FeeEngine(
            self.data.exchange, settings.fee_rate, force_static=settings.fee_force_static
        )

        self.preflight = PreFlightValidator(

            self.fee_engine,

            slippage_buffer_pct=settings.slippage_buffer_pct,

            min_net_profit_pct=settings.min_net_profit_pct,

        )

        self.circuit_breaker = CircuitBreaker(

            risk_state=self.broker.risk,

            drawdown_limit_pct=settings.drawdown_hibernate_pct,

            save_callback=self.broker.save,

            diagnostic_dir=settings.diagnostic_dir,

        )

        self.constraints = PortfolioConstraints(

            min_eth_reserve=settings.min_eth_reserve,

            max_alt_allocation_pct=settings.max_alt_allocation_pct,

            min_usd_trade=settings.min_usd_trade,

        )

        self.governor = StrategyGovernor(

            self.broker.risk,

            growth_window_hours=settings.strategy_growth_window_hours,

            min_growth_pct=settings.strategy_min_growth_pct,

            strong_growth_pct=settings.strategy_strong_growth_pct,

            switch_edge_margin=settings.strategy_switch_edge_margin,

            exploration_ratio=settings.strategy_exploration_ratio,

            save_callback=self.broker.save,

        )

        self._governor_status = None

        webhook = settings.discord_webhook or settings.alert_discord_webhook

        self.alerts = AlertManager(

            AlertConfig(

                enabled=settings.alerts_enabled,

                discord_webhook=webhook,

                telegram_bot_token=settings.alert_telegram_bot_token,

                telegram_chat_id=settings.alert_telegram_chat_id,

                smtp_host=settings.alert_smtp_host,

                smtp_port=settings.alert_smtp_port,

                smtp_user=settings.alert_smtp_user,

                smtp_password=settings.alert_smtp_password,

                email_from=settings.alert_email_from,

                email_to=settings.alert_email_to,

                twilio_sid=settings.alert_twilio_sid,

                twilio_token=settings.alert_twilio_token,

                twilio_from=settings.alert_twilio_from,

                sms_to=settings.alert_sms_to,

            )

        )

        self.discord = DiscordBot(

            DiscordConfig(

                enabled=settings.discord_enabled,

                webhook_url=webhook,

                bot_token=settings.discord_bot_token,

                channel_id=settings.discord_channel_id,

                allowed_user_ids=frozenset(settings.discord_allowed_user_ids),

                error_cooldown_sec=settings.discord_error_cooldown_minutes * 60,

                error_pin_count=settings.discord_error_pin_count,

                error_pin_window_sec=settings.discord_error_pin_window_minutes * 60,

                pin_enabled=settings.discord_pin_enabled,

                max_pins_retain=settings.discord_max_pins_retain,

                chat_log_enabled=settings.discord_chat_log_enabled,

                chat_log_file=ROOT / settings.discord_chat_log_file,

            ),

            command_handler=self._handle_discord_command,

        )

        self.discord.on_error = self._report_error

        self._last_status_key: str | None = None

        self._status_since: str | None = None

        self._last_result = None

        self._instance_started_at: str | None = None

        self._last_heartbeat_monotonic: float = 0.0

        self._last_pinned_pnl_band: int = 0

        self._shutdown_done = False

        self._restart_requested: bool = False

        self._restart_reason: str = ""

        self.watchdog = WatchdogService(
            settings,
            self.runtime,
            post_alert=self._watchdog_alert,
            is_trading_active=self.runtime.is_trading_active,
            pause_trading=lambda: self.runtime.set_trading_active(False),
        )

        self.auditor = AuditorService(
            settings,
            AuditorConfig(
                enabled=settings.auditor_enabled,
                daily_run_hour_pacific=settings.auditor_daily_run_hour_pacific,
                trade_count_trigger=settings.auditor_trade_count_trigger,
                pnl_pct_trigger=settings.auditor_pnl_pct_trigger,
                news_enabled=settings.auditor_news_enabled,
                news_provider=settings.auditor_news_provider,
                cryptopanic_api_key=settings.auditor_cryptopanic_api_key,
                rss_feeds=settings.auditor_rss_feeds,
                news_max_items=settings.auditor_news_max_items,
                proposals_ttl_minutes=settings.auditor_proposals_ttl_minutes,
                reports_dir=settings.auditor_reports_dir,
                state_file=settings.auditor_state_file,
                autoapply_enabled=settings.auditor_autoapply_enabled,
                autoapply_window_start_hour=settings.auditor_autoapply_window_start_hour,
                autoapply_window_end_hour=settings.auditor_autoapply_window_end_hour,
                autoapply_min_severity=settings.auditor_autoapply_min_severity,
                autoapply_max_per_night=settings.auditor_autoapply_max_per_night,
                autoapply_restart_enabled=settings.auditor_autoapply_restart_enabled,
                confirm_restart_enabled=settings.auditor_confirm_restart_enabled,
                chat_enabled=settings.auditor_chat_enabled,
                chat_backend=settings.auditor_chat_backend,
                chat_model=settings.auditor_chat_model,
                chat_api_key=settings.auditor_chat_api_key,
                chat_max_turns=settings.auditor_chat_max_turns,
                chat_max_tokens=settings.auditor_chat_max_tokens,
                chat_temperature=settings.auditor_chat_temperature,
                chat_tool_iterations=settings.auditor_chat_tool_iterations,
                chat_tool_result_max_chars=settings.auditor_chat_tool_result_max_chars,
            ),
            broker=self.broker,
            governor=self.governor,
            discord=self.discord,
            portfolio_log=self.portfolio_log,
            watchdog_state_provider=lambda: None,
            request_restart=self.request_restart,
        )



    def _handle_auditor_command(self, command: str, user_id: str = "") -> str:

        token, _, args = command.partition(" ")

        args = args.strip()

        if token == "auditor-review":

            report = self.auditor.run_audit(trigger="manual")

            path = report.markdown_path

            tail = f"\n\nFull report: `{path}`" if path else ""

            return report.summary + tail

        if token == "auditor-forecast":

            report = self.auditor.run_audit(trigger="manual-forecast")

            path = report.markdown_path

            tail = f"\n\nFull report: `{path}`" if path else ""

            return report.summary + tail

        if token == "auditor-strategy":

            report = self.auditor.run_audit(trigger=f"manual-strategy:{args or 'all'}")

            path = report.markdown_path

            tail = f"\n\nFull report: `{path}`" if path else ""

            return report.summary + tail

        if token == "auditor-summary":

            report = self.auditor.run_audit(trigger="manual-summary")

            return report.summary

        if token == "auditor-confirm":

            return self.auditor.confirm_proposal(args)

        if token == "auditor-pending":

            return self.auditor.list_pending()

        if token == "auditor-revert":

            return self.auditor.revert(args)

        if token == "auditor-status":

            return self.auditor.status()

        if token == "auditor-ask":

            return self.auditor.ask(args)

        if token == "auditor-chat":

            return self.auditor.chat(user_id or "global", args)

        if token == "auditor-clearchat":

            return self.auditor.clear_chat(user_id or "global")

        if token == "auditor-chatstatus":

            return self.auditor.chat_status()

        return f"Unknown auditor command `{token}` — send `Auditor -help` for options."



    def _watchdog_alert(self, message: str, pin: bool) -> None:

        if not self.settings.discord_enabled:

            logger.warning("Watchdog: %s", message.replace("\n", " ")[:240])

            return

        self.discord.post_important(message, pin=pin, source="WatchDog")



    def _holdings(self) -> dict[str, float]:

        return dict(self.broker.state.balances)

    def _write_portfolio_file(
        self,
        *,
        holdings: dict[str, float],
        usd_prices: dict[str, float],
        portfolio: float,
        baseline_pnl: float,
        drawdown: float,
    ) -> None:
        try:
            self.portfolio_log.write(
                holdings=holdings,
                usd_prices=usd_prices,
                portfolio_usd=portfolio,
                baseline_pnl=baseline_pnl,
                drawdown_pct=drawdown,
            )
        except OSError as exc:
            logger.warning("Could not write portfolio file: %s", exc)

    def _seed_portfolio_snapshot(self) -> None:
        """Ensure ``paper_portfolio.json`` exists before the first tick."""
        try:
            snapshot = self._refresh_market_view()
            self._write_portfolio_file(
                holdings=snapshot.holdings,
                usd_prices=snapshot.usd_prices,
                portfolio=snapshot.portfolio,
                baseline_pnl=snapshot.baseline_pnl,
                drawdown=snapshot.drawdown,
            )
            return
        except Exception as exc:
            logger.warning("Startup portfolio refresh failed: %s", exc)
        if not self.portfolio_log.load():
            self.portfolio_log.bootstrap_from_state(self.settings.state_file)

    def _startup_portfolio_view(self) -> tuple[dict[str, float], str | None]:
        """Load display balances from portfolio file when available."""
        snap = self.portfolio_log.load()
        live = {k: v for k, v in self._holdings().items() if v > 0}
        if snap and snap.balances():
            return snap.balances(), snap.summary_line()
        return live, None

    def _active_overrides_line(self) -> str:
        """Render active `runtime_overrides.json` knobs for the startup pin.

        Returns empty string when no overrides are active. This is the user's
        primary visual confirmation that an `Auditor -confirm` was picked up
        by a full process restart (vs. just `stop`/`start`).
        """
        from bot.auditor.runtime_overrides import list_overrides

        overrides_file = Path(__file__).resolve().parent.parent / "runtime_overrides.json"
        try:
            overrides = list_overrides(overrides_file)
        except Exception as exc:  # noqa: BLE001 — never block startup
            logger.warning("Could not read runtime_overrides.json: %s", exc)
            return ""
        if not overrides:
            return ""
        rendered = ", ".join(f"`{k}`={v}" for k, v in sorted(overrides.items()))
        return f":gear: Auditor overrides active: {rendered}"



    def _usd_prices(self) -> dict[str, float]:

        assets = list(self._holdings().keys())

        return self.data.fetch_usd_prices(assets)



    def _pair_price(self, pair_symbol: str) -> float:

        return self.data.fetch_ticker(pair_symbol)



    def _build_context(self) -> StrategyContext:

        pair_symbols = list(self.markets.all_symbols())

        pair_prices = self.data.fetch_pair_prices(pair_symbols)

        candles_by_tf = self.data.fetch_multi_timeframe_candles()

        return StrategyContext(

            candles_by_timeframe=candles_by_tf,

            pair_prices=pair_prices,

        )



    def _execute_intent(self, intent, usd_prices: dict[str, float]) -> dict | None:

        route = getattr(intent, "route", None) or self.markets.find_path(
            intent.from_asset, intent.to_asset
        )

        if not route:

            return None



        prices = {symbol: self._pair_price(symbol) for symbol in route.symbols}

        return self.broker.execute_path(

            route=route,

            prices=prices,

            usd_prices=usd_prices,

            reason=intent.reason,

            size_pct=intent.size_pct,

            strategy_name=intent.strategy_name,

        )



    def _intent_trade_usd(self, intent, holdings, usd_prices) -> float:

        qty = holdings.get(intent.from_asset, 0.0) * intent.size_pct

        return qty * usd_prices.get(intent.from_asset, 1.0 if intent.from_asset == "USD" else 0.0)



    def _active_strategy_names(self) -> list[str]:

        plugins = getattr(self.strategy, "strategies", None)

        if plugins:

            return [s.name for s in plugins]

        return [self.strategy.name]



    def _format_strategy_discord(self) -> str:

        return format_strategy_status(

            configured=self.settings.strategies,

            active_names=self._active_strategy_names(),

            last_result=self._last_result,

            governor_status=self._governor_status,

            governor_summary=self.governor.strategy_summary() if self._governor_status else "",

        )



    def _post_strategy_status(self) -> None:

        if not self.settings.discord_enabled or not self.discord.config.can_post_status:

            return

        self.discord.post_plain(self._format_strategy_discord())



    def _risk_note(self) -> str:

        if self.risk.is_paused():

            note = self.risk.pause_status()

            if self.circuit_breaker.in_reevaluation():

                note = self.circuit_breaker.status_message() or note

            return note

        if not self.runtime.is_trading_active():

            return "Bot STOPPED via Discord — send `start` to resume ticks"

        adaptive = self.risk.adaptive_status()

        if adaptive.active:

            return (

                f"ADAPTIVE MODE — {adaptive.idle_hours:.1f}h without trades; "

                f"thresholds at {adaptive.relax_factor:.0%} of normal "

                f"(attempt {adaptive.relax_attempts + 1}/{adaptive.max_relax_attempts}; fee floor enforced)"

            )

        if adaptive.suspended:

            return "ADAPTIVE SUSPENDED — strict thresholds until next trade or reset"

        return ""



    def _report_error(self, context: str, exc: BaseException) -> None:

        logger.error("%s: %s", context, exc)

        if self.settings.discord_enabled:

            self.discord.post_error(context, exc)



    def _maybe_force_probe(self, intents, result, holdings, usd_prices, portfolio, trades) -> None:
        """Guaranteed-activity valve. If nothing traded this tick and the bot has
        been idle past ``idle_probe_force_minutes``, take ONE small trade that
        ignores the edge/fee gates so there is visible action. Paper-only — this
        may lose fees by design; it exists so a flat market doesn't look frozen.
        """
        if trades:
            return
        minutes = self.settings.idle_probe_force_minutes
        if minutes <= 0 or not self.runtime.is_trading_active():
            return
        if self.risk.idle_hours() * 60.0 < minutes:
            return
        import time as _t
        last = getattr(self, "_last_probe_monotonic", 0.0)
        if _t.monotonic() - last < max(60.0, minutes * 30.0):
            return
        self._last_probe_monotonic = _t.monotonic()

        intent = self._pick_probe_candidate(intents, result, holdings, usd_prices)
        if intent is None:
            return
        intent.size_pct = min(intent.size_pct or 1.0, max(0.01, self.settings.idle_probe_size_pct))
        intent.is_defensive = False
        intent.reason = (
            "Forced probe \u2014 no setup cleared the bar while idle; trading small "
            "on a candidate that still clears fees + slippage"
        )

        # Break-even gate: a probe exists to keep the bot active, NOT to bleed
        # fees. Re-check the candidate through pre-flight with LIVE fees and a
        # zero-profit floor; if it cannot clear real fees + slippage we skip it
        # entirely. This makes IDLE_PROBE_FORCE_MINUTES safe to leave enabled —
        # it can only ever fire a non-losing trade.
        probe_route = getattr(intent, "route", None) or self.markets.find_path(
            intent.from_asset, intent.to_asset
        )
        if not probe_route:
            return
        probe_pf = self.preflight.validate(
            intent,
            route_symbols=probe_route.symbols,
            hops=probe_route.hops,
            is_defensive=False,
            min_net_profit=0.0,
        )
        if not probe_pf.allowed:
            logger.info("Forced probe skipped — would not clear fees: %s", probe_pf.reason)
            return
        intent.edge = probe_pf.net_return_pct

        trade = self._execute_intent(intent, usd_prices)
        if not trade:
            return
        trade["edge"] = intent.edge
        trade["gross_return_pct"] = intent.gross_return_pct
        trade["is_defensive"] = False
        trade["is_expansion"] = False
        trade["is_held_swap"] = intent.is_held_swap
        trade["is_probe"] = True
        receipt_path = self.receipts.save(trade)
        trade["receipt_file"] = str(receipt_path)
        trades.append(trade)
        self.governor.record_trade(
            intent.strategy_name or "probe", portfolio, float(trade.get("gain_loss", 0.0))
        )
        self.risk.record_trade()
        self.auditor.note_trade(trade)
        if self.settings.discord_enabled:
            self.discord.post_important(
                "\U0001F0CF **Forced probe trade** \u2014 no setup cleared the bar while "
                "idle, so I took a small one to keep things active. Paper test; may lose fees.",
                pin=False,
            )

    def _probe_respects_eth_reserve(self, from_asset: str, holdings: dict[str, float]) -> bool:
        """A probe must never sell ETH below the configured reserve floor.

        The probe bypasses the normal constraint pipeline (that's the point —
        it ignores edge/fee gates), so the ETH-reserve protection has to be
        re-applied here explicitly.
        """
        if from_asset != "ETH":
            return True
        size = max(0.01, self.settings.idle_probe_size_pct)
        return holdings.get("ETH", 0.0) * (1.0 - size) >= self.settings.min_eth_reserve

    def _pick_probe_candidate(self, intents, result, holdings, usd_prices):
        """Choose what to probe, preferring genuine diversification.

        Order of preference (intents + opportunities searched together):
          1. A candidate whose destination we do NOT already hold (so a string
             of forced probes spreads across coins instead of piling into the
             same one), respecting the ETH reserve.
          2. Any candidate that respects the ETH reserve.
          3. Safe fallbacks: diversify spare USD into an unheld core coin, or
             trim a sliver of the largest over-reserve holding to USD.
        """
        from bot.strategies.base import TradeIntent

        held = {a for a, q in holdings.items() if q > 0 and a != "USD"}

        def _as_intent(src) -> TradeIntent:
            # ``src`` is either a TradeIntent (actionable, gate-blocked) or a
            # RotationOption (a considered opportunity). Normalise to a probe
            # intent either way.
            if isinstance(src, TradeIntent):
                return TradeIntent(
                    from_asset=src.from_asset,
                    to_asset=src.to_asset,
                    reason=src.reason,
                    size_pct=src.size_pct or 0.05,
                    edge=src.edge,
                    gross_return_pct=src.gross_return_pct,
                    is_held_swap=src.is_held_swap,
                    strategy_name=src.strategy_name or "probe",
                )
            return TradeIntent(
                from_asset=src.from_asset,
                to_asset=src.to_asset,
                reason=f"probe via {getattr(src, 'category', 'rotation')}",
                size_pct=0.05,
                edge=getattr(src, "edge", 0.0),
                gross_return_pct=getattr(src, "edge", 0.0),
                strategy_name="probe",
            )

        opportunities = list(getattr(result, "opportunities", None) or [])
        # Intents are the ranked/actionable candidates; opportunities are the
        # broader "considered" set. Search both so a run of forced probes keeps
        # rotating into NEW coins instead of piling into the one intent the
        # strategy happened to emit.
        candidates = list(intents) + opportunities

        # 1) diversify: first candidate into a coin we don't hold yet
        for cand in candidates:
            if cand.to_asset in held or cand.to_asset == "USD":
                continue
            if self._probe_respects_eth_reserve(cand.from_asset, holdings):
                return _as_intent(cand)
        # 2) any candidate that keeps ETH above its reserve
        for cand in candidates:
            if self._probe_respects_eth_reserve(cand.from_asset, holdings):
                return _as_intent(cand)

        # 3) fallbacks. Prefer putting spare USD to work in an unheld core coin.
        live = {a: q for a, q in holdings.items() if q > 0}
        if live.get("USD", 0.0) > self.settings.min_usd_trade:
            for core in self.settings.core_assets:
                if core != "USD" and core not in held:
                    return TradeIntent(
                        from_asset="USD", to_asset=core, reason=f"probe diversify into {core}",
                        size_pct=0.05, edge=0.0, gross_return_pct=0.0, strategy_name="probe",
                    )
            return TradeIntent(
                from_asset="USD", to_asset="ETH", reason="probe into ETH",
                size_pct=0.05, edge=0.0, gross_return_pct=0.0, strategy_name="probe",
            )
        # else trim a sliver of the largest holding that respects the ETH reserve
        non_usd = {
            a: q * usd_prices.get(a, 0.0)
            for a, q in live.items()
            if a != "USD" and self._probe_respects_eth_reserve(a, holdings)
        }
        if non_usd:
            asset = max(non_usd, key=non_usd.get)
            return TradeIntent(
                from_asset=asset, to_asset="USD", reason="probe to USD",
                size_pct=0.05, edge=0.0, gross_return_pct=0.0, strategy_name="probe",
            )
        return None

    def _notify_discord_trades(
        self, trades: list[dict], portfolio: float, baseline_pnl: float
    ) -> None:
        if not self.settings.discord_enabled or not trades:
            return
        threshold = self.settings.discord_pin_trade_usd
        for trade in trades:
            gain = float(trade.get("gain_loss", 0.0))
            pin = abs(gain) >= threshold
            msg = format_trade_executed_alert(trade, portfolio, baseline_pnl)
            if pin:
                direction = "gain" if gain >= 0 else "loss"
                msg = msg.replace(
                    "**Trade executed**",
                    f"**Major trade {direction} — ${abs(gain):,.2f}**",
                    1,
                )
            self.discord.post_important(msg, pin=pin)



    def _maybe_pin_pnl_milestone(self, portfolio: float, baseline_pnl: float) -> None:

        if not self.settings.discord_enabled:

            return

        baseline = self.risk.state.baseline_portfolio

        threshold = self.settings.discord_pin_pnl_pct

        band = pnl_milestone_band(baseline_pnl, baseline, threshold)

        if band == 0 or band == self._last_pinned_pnl_band:

            return

        self._last_pinned_pnl_band = band

        self.discord.post_important(

            format_pnl_milestone_alert(

                portfolio,

                baseline_pnl,

                baseline,

                band=band,

                threshold_pct=threshold,

            ),

            pin=True,

        )



    def _refresh_market_view(self) -> TickSnapshot:

        usd_prices = self._usd_prices()

        candles = self.data.fetch_all_candles()

        holdings = self._holdings()

        portfolio = self.broker.portfolio_value(usd_prices)

        self.risk.update_portfolio(portfolio)

        result = self.strategy.evaluate(

            candles, usd_prices, holdings, risk=self.risk, markets=self.markets,

            context=self._build_context(),

        )

        self._last_result = result

        status = build_status_snapshot(

            result,

            [],

            list(result.blocked),

            is_paused=self.risk.is_paused(),

            pause_message=self.risk.pause_status() if self.risk.is_paused() else "",

        )

        now = format_pacific()

        snapshot = TickSnapshot(

            portfolio=portfolio,

            baseline_pnl=self.risk.pnl_from_baseline(portfolio),

            drawdown=self.risk.drawdown_pct(portfolio),

            holdings=holdings,

            usd_prices=usd_prices,

            status=status,

            trades=[],

            status_since=self._status_since,

            updated_at=now,

        )

        self.runtime.update_snapshot(snapshot)

        return snapshot



    def _handle_discord_command(self, command: str, user_id: str) -> str:

        if command == "help":

            return HelpText



        if command == "tradebot-help":

            return TradeBotHelpText



        if command == "watchdog-help":

            return WatchDogHelpText



        if command == "auditor-help":

            return AuditorHelpText



        if command.startswith("auditor-"):

            return self._handle_auditor_command(command, user_id)



        if command == "clearchat":

            deleted, skipped = self.discord.clear_recent_messages()

            summary = f"WatchDog cleared {deleted} message{'s' if deleted != 1 else ''}."

            if skipped:

                summary += f" Skipped {skipped} pinned."

            self.discord.chat_log.log_event(

                f"WatchDog clearchat: deleted={deleted}, skipped={skipped}"

            )

            return summary



        if command == "strategy":

            snapshot = self._refresh_market_view()

            body = self._format_strategy_discord()

            return f"{body}\n\n_Updated {snapshot.updated_at}_"



        if command == "watchdog":

            return self.watchdog.status_text()



        if command == "watchdog-pause":

            return self.watchdog.pause_bot()



        if command == "start":

            self.runtime.set_trading_active(True)

            return (
                "Trading **started** — bot will resume market ticks.\n"
                "_(Note: `start`/`stop` only toggle ticks; they do not restart the process "
                "or reload `runtime_overrides.json`. For auditor overrides to take effect, "
                "fully quit and re-run `main.py`.)_"
            )



        if command == "stop":

            self.runtime.set_trading_active(False)

            return (
                "Trading **stopped** — no new ticks until you send `start`.\n"
                "_(Note: this does NOT restart the Python process. If you just confirmed "
                "an `Auditor -confirm`, you still need to fully quit and re-run `main.py` "
                "for the override to load.)_"
            )



        if command == "resume-trading":

            if not self.circuit_breaker.in_reevaluation():

                return "Not in re-evaluation mode — circuit breaker is not active."

            self.circuit_breaker.clear_reevaluation()

            self.risk.state.paused_until = None

            self.risk.state.hibernate_alert_sent = False

            self.broker.save()

            return (

                "Re-evaluation mode **cleared** — send `start` if trading was stopped. "

                "Peak watermark unchanged; monitor drawdown closely."

            )



        if command == "reset":

            self.broker.reset_state()

            self.circuit_breaker.clear_reevaluation()

            self._last_status_key = None

            self._status_since = None

            self._last_result = None

            self._last_pinned_pnl_band = 0

            self._instance_started_at = format_pacific()

            if self.watchdog.enabled:

                self.watchdog.reset(silent=True)

            channel_stats = self.discord.reset_discord_channel()

            self.discord.chat_log.log_event(

                "TradeBot reset: "

                f"pins_cleared={channel_stats['pins_cleared']}, "

                f"deleted={channel_stats['deleted']}, "

                f"skipped={channel_stats['skipped']}, "

                "error_counters=TradeBot+WatchDog cleared"

            )

            self.discord.post_startup_pin(

                f"**Trading bot started and active**\n"

                f"Paper state reset {self._instance_started_at}"

            )

            self._post_strategy_status()

            snapshot = self._refresh_market_view()

            self._write_portfolio_file(
                holdings=snapshot.holdings,
                usd_prices=snapshot.usd_prices,
                portfolio=snapshot.portfolio,
                baseline_pnl=snapshot.baseline_pnl,
                drawdown=snapshot.drawdown,
            )

            return (

                "Paper state **reset** to initial balances.\n"

                f"Discord: cleared **{channel_stats['pins_cleared']}** pin(s), "

                f"deleted **{channel_stats['deleted']}** message(s).\n"

                "TradeBot + WatchDog error counters cleared.\n```\n"

                + format_portfolio_summary(

                    portfolio=snapshot.portfolio,

                    baseline_pnl=snapshot.baseline_pnl,

                    drawdown=snapshot.drawdown,

                    holdings=snapshot.holdings,

                    usd_prices=snapshot.usd_prices,

                    trading_active=self.runtime.is_trading_active(),

                    risk_note=self._risk_note(),

                )

                + "\n```"

            )



        snapshot = self._refresh_market_view()

        if not snapshot.status:

            return "No market snapshot available yet."



        if command == "portfolio":

            return "```\n" + format_portfolio_summary(

                portfolio=snapshot.portfolio,

                baseline_pnl=snapshot.baseline_pnl,

                drawdown=snapshot.drawdown,

                holdings=snapshot.holdings,

                usd_prices=snapshot.usd_prices,

                trading_active=self.runtime.is_trading_active(),

                risk_note=self._risk_note(),

            ) + f"\n\nUpdated {snapshot.updated_at}\n```"



        if command == "planned":

            return "```\n" + format_planned_actions(

                snapshot.status,

                status_since=snapshot.status_since,

            ) + f"\n\nUpdated {snapshot.updated_at}\n```"



        return f"Unknown command `{command}` — send `help` for options."



    def tick(self) -> float:

        started = time.monotonic()



        usd_prices = self._usd_prices()

        candles = self.data.fetch_all_candles()

        holdings = self._holdings()



        portfolio = self.broker.portfolio_value(usd_prices)

        self.governor.set_portfolio_snapshot(portfolio)

        self.governor.update_growth(portfolio)

        allow_hibernate = not self.settings.circuit_breaker_enabled

        hibernate_event = self.risk.update_portfolio(

            portfolio, allow_timed_hibernate=allow_hibernate

        )

        cb_event = None

        if self.settings.circuit_breaker_enabled:

            cb_event = self.circuit_breaker.check(portfolio)

            if cb_event:

                self.risk.state.paused_until = None

                self.broker.save()

                path = self.circuit_breaker.dump_diagnostics(

                    cb_event, holdings, usd_prices,

                    extra={"strategies": getattr(self.strategy, "name", "")},

                )

                if self.settings.discord_enabled:

                    self.discord.post_important(

                        f"**CIRCUIT BREAKER** — portfolio ${cb_event.portfolio_value:,.2f}, "

                        f"drawdown {cb_event.drawdown_pct:.1%} from peak. "

                        f"Re-evaluation mode — manual `resume-trading` required.\n"

                        f"Diagnostic: `{path.name}`",

                        pin=True,

                    )

        elif hibernate_event:

            self._send_hibernate_alert(hibernate_event, portfolio)

        elif self.risk.needs_hibernate_alert():

            until = self.risk.state.paused_until

            if until:

                self._send_hibernate_alert(

                    HibernateEvent(

                        portfolio_value=portfolio,

                        peak_portfolio=self.risk.state.peak_portfolio,

                        drawdown_pct=self.risk.drawdown_pct(portfolio),

                        resume_at=datetime.fromisoformat(until),

                    ),

                    portfolio,

                )

        adaptive_msg = self.risk.check_adaptive_notification()

        if adaptive_msg and self.settings.discord_enabled:

            self.discord.post_plain(adaptive_msg)



        context = self._build_context()

        result = self.strategy.evaluate(

            candles, usd_prices, holdings, risk=self.risk, markets=self.markets,

            context=context,

        )

        self._last_result = result

        self.broker.ensure_cost_basis(usd_prices)



        trades: list[dict] = []

        blocked: list[str] = list(result.blocked)

        intents = list(result.intents)

        trim_intents = self.constraints.trim_overweight_intents(

            holdings, usd_prices, self.markets.find_path

        )

        if trim_intents:

            intents = trim_intents + intents

        intents, self._governor_status, gov_notes = self.governor.apply(

            intents,

            adaptive=self.risk.adaptive_status().active,

        )

        if gov_notes:

            blocked.extend(gov_notes)

        if cb_event:

            intents = self.circuit_breaker.defensive_intents(

                holdings,

                usd_prices,

                self.settings.safe_assets,

                self.settings.dust_usd,

            ) + intents



        in_reevaluation = self.circuit_breaker.in_reevaluation()

        can_trade = self.runtime.is_trading_active() and (

            not self.risk.is_paused() or in_reevaluation

        )

        if can_trade:

            adaptive_active = self.risk.adaptive_status().active

            if adaptive_active and intents:

                exhausted_msg = self.risk.record_adaptive_attempt()

                if exhausted_msg:

                    blocked.append(exhausted_msg)

                    if self.settings.discord_enabled:

                        self.discord.post_plain(exhausted_msg)

            for intent in intents:

                if in_reevaluation and not intent.is_defensive:

                    blocked.append(

                        f"Re-evaluation mode — blocked {intent.from_asset}->{intent.to_asset}"

                    )

                    continue

                route = getattr(intent, "route", None) or self.markets.find_path(
                    intent.from_asset, intent.to_asset
                )

                if not route:

                    blocked.append(f"No route: {intent.from_asset} -> {intent.to_asset}")

                    continue



                trade_usd = self._intent_trade_usd(intent, holdings, usd_prices)

                required_edge = self.risk.path_edge(

                    route.hops, is_held_swap=intent.is_held_swap

                )

                constraint = self.constraints.validate_intent(

                    intent,

                    holdings,

                    usd_prices,

                    required_edge=required_edge,

                )

                if not constraint.allowed:

                    blocked.append(constraint.reason)

                    continue

                intent.size_pct = constraint.size_pct

                trade_usd = self._intent_trade_usd(intent, holdings, usd_prices)

                pf = self.preflight.validate(

                    intent,

                    route_symbols=route.symbols,

                    hops=route.hops,

                    is_defensive=intent.is_defensive,

                    min_net_profit=self.risk.effective_min_net_profit(),

                )

                if not pf.allowed:

                    blocked.append(pf.reason)

                    continue

                intent.edge = pf.net_return_pct



                approval = self.risk.approve_action(

                    "buy" if intent.to_asset != "USD" else "sell",

                    intent.edge,

                    trade_usd,

                    is_defensive_sell=intent.is_defensive,

                    is_held_swap=intent.is_held_swap,

                    hops=route.hops,

                    require_leader_stable=intent.require_leader_stable,

                )

                if not approval.allowed:

                    blocked.append(approval.reason)

                    continue



                trade = self._execute_intent(intent, usd_prices)

                if trade:

                    trade["edge"] = intent.edge

                    trade["gross_return_pct"] = intent.gross_return_pct

                    trade["is_defensive"] = intent.is_defensive

                    trade["is_expansion"] = intent.is_expansion

                    trade["is_held_swap"] = intent.is_held_swap

                    receipt_path = self.receipts.save(trade)

                    trade["receipt_file"] = str(receipt_path)

                    trades.append(trade)

                    self.governor.record_trade(

                        intent.strategy_name or "unknown",

                        portfolio,

                        float(trade.get("gain_loss", 0.0)),

                    )

                    self.risk.record_trade()

                    self.auditor.note_trade(trade)

                    break

            self._maybe_force_probe(intents, result, holdings, usd_prices, portfolio, trades)

        status = build_status_snapshot(

            result,

            trades,

            blocked,

            is_paused=self.risk.is_paused(),

            pause_message=self.risk.pause_status() if self.risk.is_paused() else "",

        )

        status_changed = bool(trades) or status.summary_key != self._last_status_key

        if status_changed:

            self._status_since = format_pacific()

            self._last_status_key = status.summary_key



        baseline_pnl = self.risk.pnl_from_baseline(portfolio)

        drawdown = self.risk.drawdown_pct(portfolio)

        risk_note = self._risk_note()



        self._notify_discord_trades(trades, portfolio, baseline_pnl)

        self._maybe_pin_pnl_milestone(portfolio, baseline_pnl)



        self.runtime.update_snapshot(

            TickSnapshot(

                portfolio=portfolio,

                baseline_pnl=baseline_pnl,

                drawdown=drawdown,

                holdings=dict(holdings),

                usd_prices=dict(usd_prices),

                status=status,

                trades=list(trades),

                status_since=self._status_since,

                updated_at=format_pacific(),

            )

        )



        self.file_log.log_tick(

            portfolio=portfolio,

            baseline_pnl=baseline_pnl,

            drawdown=drawdown,

            result=result,

            holdings=self._holdings(),

            usd_prices=usd_prices,

            blocked=blocked,

            trades=trades,

            status=status,

            status_changed=status_changed,

            status_since=self._status_since,

            find_path_fn=self.markets.find_path,

        )

        self._write_portfolio_file(
            holdings=holdings,
            usd_prices=usd_prices,
            portfolio=portfolio,
            baseline_pnl=baseline_pnl,
            drawdown=drawdown,
        )



        elapsed = time.monotonic() - started

        self.display.tick(

            portfolio=portfolio,

            usd_prices=usd_prices,

            holdings=self._holdings(),

            trades=trades,

            status=status,

            status_changed=status_changed,

            status_since=self._status_since,

            elapsed=elapsed,

            poll_interval=self.settings.poll_interval,

            risk=self.risk,

            baseline_pnl=baseline_pnl,

            drawdown=drawdown,

        )



        return elapsed



    def _send_hibernate_alert(self, event, portfolio: float) -> None:

        resume_at = format_pacific(event.resume_at, "%Y-%m-%d %H:%M %Z")

        errors = self.alerts.send_hibernate_alert(

            portfolio=event.portfolio_value,

            peak=event.peak_portfolio,

            drawdown_pct=event.drawdown_pct,

            drawdown_limit_pct=self.settings.drawdown_hibernate_pct,

            resume_at=resume_at,

            baseline_pnl=self.risk.pnl_from_baseline(portfolio),

        )

        self.risk.mark_hibernate_alert_sent()

        if self.settings.discord_enabled:

            self.discord.post_important(

                f"**HIBERNATING** — portfolio ${event.portfolio_value:,.2f}, "

                f"drawdown {event.drawdown_pct:.1%}, resumes {resume_at}",

                pin=True,

            )

        if not errors and self.settings.alerts_enabled:

            logger.warning("Hibernation alert sent — bot paused until %s", resume_at)

        elif self.settings.alerts_enabled and not self.alerts.config.has_any_channel:

            logger.warning(

                "Hibernation triggered but no alert channels configured in .env"

            )



    def _discord_startup(self) -> None:

        if not self.settings.discord_enabled or not self.discord.config.can_post_status:

            return

        self._instance_started_at = format_pacific()

        try:

            self._refresh_market_view()

        except Exception as exc:

            logger.warning("Startup market refresh failed: %s", exc)

        overrides_line = self._active_overrides_line()

        startup_text = (
            f"**Trading bot started and active**\n"
            f"Started {self._instance_started_at}"
        )

        if overrides_line:
            startup_text = f"{startup_text}\n{overrides_line}"

        self.discord.post_startup_pin(startup_text)

        self._post_strategy_status()

        self._last_heartbeat_monotonic = time.monotonic()



    def _post_discord_heartbeat(self) -> None:

        if not self.settings.discord_enabled or not self.discord.config.can_post_status:

            return

        if not self._instance_started_at:

            self._instance_started_at = format_pacific()

        self.discord.post_plain(f"Monitoring exchange since {self._instance_started_at}")

        self._last_heartbeat_monotonic = time.monotonic()



    def _maybe_discord_heartbeat(self) -> None:

        if not self.settings.discord_enabled:

            return

        interval_sec = self.settings.discord_heartbeat_minutes * 60

        if interval_sec <= 0:

            return

        if self._last_heartbeat_monotonic <= 0:

            return

        if time.monotonic() - self._last_heartbeat_monotonic >= interval_sec:

            self._post_discord_heartbeat()



    def shutdown(self) -> None:

        if self._shutdown_done:

            return

        self._shutdown_done = True

        self.runtime.request_shutdown()

        self.auditor.stop()

        self.watchdog.stop()

        self.discord.stop()



    def request_restart(self, reason: str) -> None:
        """Mark the engine for a full process self-restart at next tick.

        Used by the auditor's sleep-window auto-apply to pick up a freshly
        written `runtime_overrides.json` without manual intervention. The
        actual ``os.execv`` happens after ``shutdown()`` so all services
        get a clean cooperative stop and state is persisted.
        """
        logger.warning("Engine self-restart requested: %s", reason)
        self._restart_reason = reason or "restart_requested"
        self._restart_requested = True
        self.runtime.request_shutdown()



    def _perform_self_restart(self) -> None:
        """Replace the current process with a fresh ``main.py`` run.

        Safe to call only after ``shutdown()`` has completed because
        ``os.execv`` immediately replaces the process image — anything not
        yet flushed to disk will be lost.

        ``--take-lock`` is injected into the child's argv so the singleton
        guard in ``main.py`` knows it is a legitimate restart and may
        overwrite the existing lock file rather than refusing to start.
        On Windows, ``os.execv`` spawns a child instead of replacing the
        current process; ``--take-lock`` prevents the child from seeing the
        still-running parent's PID and erroneously aborting.
        """
        python = sys.executable
        base_argv = [a for a in sys.argv if a != "--take-lock"]
        argv = [python, *base_argv, "--take-lock"]
        logger.warning(
            "Self-restart: exec %s argv=%s reason=%s",
            python, argv, self._restart_reason,
        )
        time.sleep(2.0)  # let Discord, watchdog flush their final messages
        try:
            os.execv(python, argv)
        except OSError as exc:
            logger.exception("os.execv failed (%s) — exiting with code 75 so a supervisor can restart us", exc)
            os._exit(75)



    def run(self) -> None:

        cross_count = sum(1 for p in self.markets.pairs.values() if p.quote != "USD")

        strategy_names = getattr(self.strategy, "strategies", None)

        strategy_label = (

            f"{self.strategy.name} ({', '.join(s.name for s in strategy_names)})"

            if strategy_names

            else self.strategy.name

        )

        self._seed_portfolio_snapshot()

        startup_balances, portfolio_summary = self._startup_portfolio_view()

        self.display.startup(

            strategy=strategy_label,

            timeframe=self.settings.candle_timeframe,

            interval=self.settings.poll_interval,

            balances=startup_balances,

            risk_note=self.risk.fee_summary(),

            usd_pairs=len(self.settings.usd_symbols),

            cross_pairs=cross_count,

            log_dir=self.settings.log_dir,

            log_file=self.file_log.current_log_file(),

            log_rotate_hours=self.settings.log_rotate_hours,

            receipts_dir=self.settings.receipts_dir,

            portfolio_summary=portfolio_summary,

            portfolio_file=self.settings.paper_portfolio_file,

        )

        self.discord.start()

        self._discord_startup()

        self.watchdog.start()

        self.auditor.start()



        try:

            while not self.runtime.should_shutdown():

                try:

                    self._maybe_discord_heartbeat()

                    if self.runtime.is_trading_active():

                        elapsed = self.tick()

                    else:

                        elapsed = 0.0

                except Exception as exc:

                    logger.exception("Tick failed")

                    self._report_error("Market tick", exc)

                    elapsed = 0.0

                time.sleep(max(0.0, self.settings.poll_interval - elapsed))

        finally:

            self.shutdown()

            if self._restart_requested:

                self._perform_self_restart()



    def run_discord_test(self) -> None:

        """Post startup + heartbeat, run one tick, then shut down."""

        print("  Discord test — posting startup and heartbeat...")

        self.discord.start()

        self._discord_startup()

        self._post_discord_heartbeat()

        try:

            print("  Discord test — running one market tick...")

            self.tick()

        except Exception as exc:

            logger.exception("Discord test tick failed")

            self._report_error("Discord test tick", exc)

            print("  Discord test — tick failed (see logs).")

        self.discord.post_plain("Trading bot test complete — shutting down.")

        self.discord.stop()

        print("  Discord test — done. Check your Discord channel for 4 messages.")


