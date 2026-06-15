from dataclasses import dataclass

from datetime import datetime, timedelta, timezone



from bot.local_time import format_pacific

from bot.adaptive import AdaptiveStatus, compute_relax_factor, fee_floor_edge, relaxed_threshold





@dataclass

class TradeGate:

    allowed: bool

    reason: str = ""





@dataclass

class HibernateEvent:

    portfolio_value: float

    peak_portfolio: float

    drawdown_pct: float

    resume_at: datetime





class RiskManager:

    """Fee-aware trade gating, drawdown hibernation, and cooldowns."""



    def __init__(

        self,

        risk_state,

        fee_rate: float,

        drawdown_hibernate_pct: float,

        hibernate_hours: float,

        trade_cooldown_seconds: int,

        max_trades_per_hour: int,

        min_trade_edge: float,

        leader_stable_seconds: int,

        fee_safety_multiplier: float,

        idle_reeval_hours: float,

        idle_reeval_max_attempts: int,

        min_net_profit_pct: float,

        stat_arb_zscore_threshold: float,

        save_callback,

        adaptive_enabled: bool = True,

        profit_only_mode: bool = False,

    ):

        self.state = risk_state

        self.fee_rate = fee_rate

        self.adaptive_enabled = adaptive_enabled

        self.profit_only_mode = profit_only_mode

        self.drawdown_hibernate_pct = drawdown_hibernate_pct

        self.hibernate_hours = hibernate_hours

        self.trade_cooldown_seconds = trade_cooldown_seconds

        self.max_trades_per_hour = max_trades_per_hour

        self.min_trade_edge = min_trade_edge

        self.leader_stable_seconds = leader_stable_seconds

        self.fee_safety_multiplier = fee_safety_multiplier

        self.idle_reeval_hours = idle_reeval_hours

        self.idle_reeval_max_attempts = idle_reeval_max_attempts

        self.min_net_profit_pct = min_net_profit_pct

        self.stat_arb_zscore_threshold = stat_arb_zscore_threshold

        self._save = save_callback



    def _now(self) -> datetime:

        return datetime.now(timezone.utc)



    def _parse(self, value: str | None) -> datetime | None:

        if not value:

            return None

        return datetime.fromisoformat(value)



    def round_trip_fee_pct(self) -> float:

        return self.fee_rate * 2



    def _base_path_edge(self, hops: int, *, is_held_swap: bool = False) -> float:

        one_way = self.fee_rate * max(1, hops)

        if is_held_swap:

            return max(self.min_trade_edge, one_way * 1.1)

        return max(self.min_trade_edge, one_way * self.fee_safety_multiplier)



    def idle_hours(self) -> float:

        anchor = self._parse(self.state.last_trade_at) or self._parse(self.state.session_started_at)

        if not anchor:

            return 0.0

        return max(0.0, (self._now() - anchor).total_seconds() / 3600.0)



    def _clear_adaptive_suspend(self) -> None:
        self.state.adaptive_suspended = False
        self.state.adaptive_suspended_at = None
        self.state.adaptive_relax_attempts = 0
        self.state.adaptive_alert_sent = False
        self._save()

    def _maybe_resume_adaptive(self, idle_hours: float) -> None:
        """Re-enable adaptive relaxation after a cooldown without a successful trade."""
        if not self.state.adaptive_suspended:
            return
        # Prolonged flat period — resume immediately instead of waiting out cooldown.
        if idle_hours >= 24.0:
            self._clear_adaptive_suspend()
            return
        suspended_at = self._parse(self.state.adaptive_suspended_at)
        if suspended_at is not None:
            hours_since = max(0.0, (self._now() - suspended_at).total_seconds() / 3600.0)
            if hours_since < self.idle_reeval_hours:
                return
        elif idle_hours < self.idle_reeval_hours * 2:
            return
        self._clear_adaptive_suspend()

    def adaptive_status(self) -> AdaptiveStatus:

        idle = self.idle_hours()

        if not self.adaptive_enabled:
            return AdaptiveStatus(
                active=False,
                idle_hours=idle,
                relax_factor=1.0,
                fee_floor_1hop=fee_floor_edge(self.fee_rate, 1),
                relax_attempts=0,
            )

        self._maybe_resume_adaptive(idle)

        if self.state.adaptive_suspended:

            return AdaptiveStatus(

                active=False,

                idle_hours=idle,

                relax_factor=1.0,

                fee_floor_1hop=fee_floor_edge(self.fee_rate, 1),

                relax_attempts=self.state.adaptive_relax_attempts,

                max_relax_attempts=self.idle_reeval_max_attempts,

                suspended=True,

            )

        relax = compute_relax_factor(idle, self.idle_reeval_hours)

        return AdaptiveStatus(

            active=relax < 1.0,

            idle_hours=idle,

            relax_factor=relax,

            fee_floor_1hop=fee_floor_edge(self.fee_rate, 1),

            relax_attempts=self.state.adaptive_relax_attempts,

            max_relax_attempts=self.idle_reeval_max_attempts,

            suspended=False,

        )



    def record_adaptive_attempt(self) -> str | None:

        """

        Count one relaxation attempt (one tick trying to trade under adaptive rules).

        After max attempts, suspend adaptive mode and restore normal thresholds.

        Returns a Discord message when exhaustion triggers, else None.

        """

        status = self.adaptive_status()

        if not status.active:

            return None

        self.state.adaptive_relax_attempts += 1

        if self.state.adaptive_relax_attempts < self.idle_reeval_max_attempts:

            self._save()

            return None

        self.state.adaptive_relax_attempts = 0

        self.state.adaptive_suspended = True
        self.state.adaptive_suspended_at = self._now().isoformat()

        self.state.adaptive_alert_sent = False

        self._save()

        return (

            f"**Adaptive relaxation exhausted** — {self.idle_reeval_max_attempts} attempts "

            f"with no qualifying trade.\n"

            f"Thresholds restored to **normal** (strict fee-aware mode).\n"

            f"Adaptive mode will not re-activate until the next successful trade or `reset`."

        )



    def effective_min_net_profit(self) -> float:

        floor = 0.0001

        if self.profit_only_mode:

            floor = max(floor, 0.0)

        result = relaxed_threshold(

            self.min_net_profit_pct, floor, self.adaptive_status().relax_factor

        )

        if self.profit_only_mode:

            return max(result, 0.0)

        return result



    def effective_stat_arb_zscore(self) -> float:

        relax = self.adaptive_status().relax_factor

        if relax >= 1.0:

            return self.stat_arb_zscore_threshold

        return max(2.0, self.stat_arb_zscore_threshold * relax)



    def effective_leader_stable_seconds(self) -> int:

        relax = self.adaptive_status().relax_factor

        if relax >= 1.0:

            return self.leader_stable_seconds

        return max(120, int(self.leader_stable_seconds * relax))



    def _ensure_session_started(self) -> None:

        if not self.state.session_started_at:

            self.state.session_started_at = self._now().isoformat()

            self._save()



    def check_adaptive_notification(self) -> str | None:

        status = self.adaptive_status()

        if not status.active or self.state.adaptive_alert_sent:

            return None

        self.state.adaptive_alert_sent = True

        self._save()

        swap = self.swap_edge()

        net = self.effective_min_net_profit()

        return (

            f"**Probe mode — hunting a trade** 🎯 no trades for {status.idle_hours:.1f}h "

            f"(threshold {self.idle_reeval_hours * 60:.0f}m).\n"

            f"Loosening edge/net-profit hurdles toward fee break-even "

            f"(relax {status.relax_factor:.0%} of normal) and will take a small "

            f"probe trade on the best candidate that still clears costs.\n"

            f"Current: swap edge {swap:+.4f} | min net {net:+.4f} | "

            f"stat-arb z ≥ {self.effective_stat_arb_zscore():.1f}σ\n"

            f"Up to {self.idle_reeval_max_attempts} relaxation attempts before thresholds reset.\n"

            f"Probes still require positive net after fees + slippage (no guaranteed losers)."

        )



    def path_edge(self, hops: int, *, is_held_swap: bool = False) -> float:

        """Minimum edge for a one-way conversion across one or more legs."""

        base = self._base_path_edge(hops, is_held_swap=is_held_swap)

        floor = fee_floor_edge(self.fee_rate, hops, is_held_swap=is_held_swap)

        return relaxed_threshold(base, floor, self.adaptive_status().relax_factor)



    def swap_edge(self) -> float:

        """Minimum relative edge for swapping between coins you already hold."""

        return self.path_edge(1, is_held_swap=True)



    def required_edge(self) -> float:

        """Minimum edge for chasing the market leader or buying with USD."""

        return self.path_edge(1, is_held_swap=False)



    def update_portfolio(self, portfolio_value: float, *, allow_timed_hibernate: bool = True) -> HibernateEvent | None:

        if self.state.baseline_portfolio <= 0:

            self.state.baseline_portfolio = portfolio_value

        self._ensure_session_started()



        if portfolio_value > self.state.peak_portfolio:

            self.state.peak_portfolio = portfolio_value



        event: HibernateEvent | None = None

        peak = self.state.peak_portfolio

        if peak > 0:

            drawdown = (peak - portfolio_value) / peak

            if drawdown >= self.drawdown_hibernate_pct and not self.is_paused() and allow_timed_hibernate:

                until = self._now() + timedelta(hours=self.hibernate_hours)

                self.state.paused_until = until.isoformat()

                self.state.hibernate_alert_sent = False

                event = HibernateEvent(

                    portfolio_value=portfolio_value,

                    peak_portfolio=peak,

                    drawdown_pct=drawdown,

                    resume_at=until,

                )



        self._roll_hour_window()

        self._save()

        return event



    def is_paused(self) -> bool:

        if getattr(self.state, "reevaluation_mode", False):

            return True

        until = self._parse(self.state.paused_until)

        if not until:

            return False

        if self._now() >= until:

            self.state.paused_until = None

            self.state.hibernate_alert_sent = False

            self._save()

            return False

        return True



    def pause_status(self) -> str:

        if getattr(self.state, "reevaluation_mode", False):

            at = getattr(self.state, "circuit_breaker_at", None)

            when = format_pacific(datetime.fromisoformat(at)) if at else "unknown"

            return (

                f"RE-EVALUATION MODE — {self.drawdown_hibernate_pct:.0%} circuit breaker at {when}. "

                "Send `resume-trading` after review."

            )

        if not self.is_paused():

            return ""

        until = self._parse(self.state.paused_until)

        drawdown = self.drawdown_pct(self.state.peak_portfolio)

        if not until:

            return f"HIBERNATING ({self.drawdown_hibernate_pct:.0%} drawdown limit hit)"

        return (

            f"HIBERNATING until {format_pacific(until, '%Y-%m-%d %H:%M %Z')} "

            f"({self.drawdown_hibernate_pct:.0%} drawdown from peak)"

        )



    def drawdown_pct(self, portfolio_value: float) -> float:

        peak = self.state.peak_portfolio

        if peak <= 0:

            return 0.0

        return max(0.0, (peak - portfolio_value) / peak)



    def pnl_from_baseline(self, portfolio_value: float) -> float:

        base = self.state.baseline_portfolio

        if base <= 0:

            return 0.0

        return portfolio_value - base



    def update_leader(self, leader_symbol: str) -> None:

        now = self._now().isoformat()

        if self.state.leader_symbol != leader_symbol:

            self.state.leader_symbol = leader_symbol

            self.state.leader_since = now

            self._save()



    def leader_is_stable(self) -> bool:

        since = self._parse(self.state.leader_since)

        if not since:

            return False

        return (self._now() - since).total_seconds() >= self.effective_leader_stable_seconds()



    def leader_stable_for(self) -> int:

        since = self._parse(self.state.leader_since)

        if not since:

            return 0

        return int((self._now() - since).total_seconds())



    def _roll_hour_window(self) -> None:

        now = self._now()

        window_start = self._parse(self.state.hour_window_start)

        if not window_start or (now - window_start).total_seconds() >= 3600:

            self.state.hour_window_start = now.isoformat()

            self.state.trades_this_hour = 0



    def cooldown_remaining(self) -> int:

        last = self._parse(self.state.last_trade_at)

        if not last:

            return 0

        elapsed = (self._now() - last).total_seconds()

        return max(0, int(self.trade_cooldown_seconds - elapsed))



    def can_trade_now(self) -> TradeGate:

        if self.is_paused():

            return TradeGate(False, self.pause_status())



        remaining = self.cooldown_remaining()

        if remaining > 0:

            return TradeGate(False, f"Cooldown active ({remaining}s remaining)")



        if self.state.trades_this_hour >= self.max_trades_per_hour:

            return TradeGate(False, f"Hourly trade limit reached ({self.max_trades_per_hour}/hr)")



        return TradeGate(True)



    def approve_action(

        self,

        side: str,

        edge: float,

        trade_usd: float,

        *,

        is_defensive_sell: bool = False,

        is_held_swap: bool = False,

        hops: int = 1,

        require_leader_stable: bool = False,

    ) -> TradeGate:

        gate = self.can_trade_now()

        if not gate.allowed:

            return gate



        fee = trade_usd * self.fee_rate * max(1, hops)

        required = self.path_edge(hops, is_held_swap=is_held_swap)



        if not is_defensive_sell and edge < required:

            label = "Swap" if is_held_swap else "Trade"

            return TradeGate(

                False,

                f"{label} edge {edge:+.4f} below fee hurdle {required:+.4f}",

            )



        if require_leader_stable and not is_defensive_sell and not is_held_swap:

            if not self.leader_is_stable():

                stable = self.leader_stable_for()

                return TradeGate(

                    False,

                    f"Leader not stable yet ({stable}s / {self.effective_leader_stable_seconds()}s)",

                )



        if trade_usd < fee * 2:

            return TradeGate(False, "Trade size too small relative to fee cost")



        return TradeGate(True, f"Approved (est. fee ${fee:.2f})")



    def record_trade(self) -> None:

        self.state.last_trade_at = self._now().isoformat()

        self.state.adaptive_alert_sent = False

        self.state.adaptive_relax_attempts = 0

        self._clear_adaptive_suspend()

        self.state.trades_this_hour += 1

        self._save()



    def fee_summary(self) -> str:

        status = self.adaptive_status()

        adaptive = ""

        if status.active:

            adaptive = (

                f" | ADAPTIVE {status.relax_factor:.0%} "

                f"({status.idle_hours:.1f}h idle)"

            )

        return (

            f"swap edge {self.swap_edge():+.4f} | "

            f"leader edge {self.required_edge():+.4f} | "

            f"2-hop edge {self.path_edge(2):+.4f} | "

            f"hibernate at {self.drawdown_hibernate_pct:.0%} drawdown for {self.hibernate_hours:.0f}h | "

            f"fee {self.fee_rate:.2%}/leg{adaptive}"

        )



    def mark_hibernate_alert_sent(self) -> None:

        self.state.hibernate_alert_sent = True

        self._save()



    def needs_hibernate_alert(self) -> bool:

        return self.is_paused() and not self.state.hibernate_alert_sent


