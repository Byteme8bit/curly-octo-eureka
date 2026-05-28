"""Strategy stickiness, growth monitoring, and controlled experimentation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from bot.strategies.base import TradeIntent


@dataclass(frozen=True)
class GovernorStatus:
    dominant_strategy: str | None
    growth_pct: float
    lock_level: str  # none | consistent | strong
    exploration_mode: bool
    notes: list[str]


def _intent_edge(intent: TradeIntent) -> float:
    return intent.gross_return_pct or intent.edge


class StrategyGovernor:
    """
    Keeps the bot agile (all strategies scan every tick) while favoring consistency:
    - Track portfolio growth over a rolling window
    - Stick with the dominant strategy when growth is consistent or strong
    - Allow bounded experimentation when growth is flat
    """

    def __init__(
        self,
        risk_state,
        *,
        growth_window_hours: float,
        min_growth_pct: float,
        strong_growth_pct: float,
        switch_edge_margin: float,
        exploration_ratio: float,
        save_callback,
    ):
        self.state = risk_state
        self.growth_window_hours = growth_window_hours
        self.min_growth_pct = min_growth_pct
        self.strong_growth_pct = strong_growth_pct
        self.switch_edge_margin = switch_edge_margin
        self.exploration_ratio = max(0.0, min(1.0, exploration_ratio))
        self._save = save_callback
        self._portfolio_value: float = 0.0

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _parse(self, value: str | None) -> datetime | None:
        if not value:
            return None
        return datetime.fromisoformat(value)

    def _reset_growth_window(self, portfolio_value: float) -> None:
        self.state.growth_window_start_at = self._now().isoformat()
        self.state.growth_window_start_value = portfolio_value

    def update_growth(self, portfolio_value: float) -> None:
        """Refresh rolling growth window anchor each tick."""
        if portfolio_value <= 0:
            return
        start_at = self._parse(self.state.growth_window_start_at)
        if not start_at or self.state.growth_window_start_value <= 0:
            self._reset_growth_window(portfolio_value)
            self._save()
            return
        hours = (self._now() - start_at).total_seconds() / 3600.0
        if hours >= self.growth_window_hours:
            self._reset_growth_window(portfolio_value)
            self._save()

    def growth_pct(self) -> float:
        start = self.state.growth_window_start_value
        if start <= 0 or self._portfolio_value <= 0:
            return 0.0
        return (self._portfolio_value - start) / start

    def set_portfolio_snapshot(self, portfolio_value: float) -> None:
        self._portfolio_value = portfolio_value

    def lock_level(self, growth_pct: float | None = None) -> str:
        g = growth_pct if growth_pct is not None else self.growth_pct()
        if g >= self.strong_growth_pct:
            return "strong"
        if g >= self.min_growth_pct:
            return "consistent"
        return "none"

    def exploration_mode(self, growth_pct: float | None = None) -> bool:
        g = growth_pct if growth_pct is not None else self.growth_pct()
        return -0.002 <= g < self.min_growth_pct

    def status(self) -> GovernorStatus:
        growth = self.growth_pct()
        return GovernorStatus(
            dominant_strategy=self.state.dominant_strategy,
            growth_pct=growth,
            lock_level=self.lock_level(growth),
            exploration_mode=self.exploration_mode(growth),
            notes=[],
        )

    def apply(
        self,
        intents: list[TradeIntent],
        *,
        adaptive: bool,
    ) -> tuple[list[TradeIntent], GovernorStatus, list[str]]:
        notes: list[str] = []
        if not intents:
            return intents, self.status(), notes

        defensive = [i for i in intents if i.is_defensive]
        offensive = [i for i in intents if not i.is_defensive]
        if not offensive:
            return intents, self.status(), notes

        growth = self.growth_pct()
        lock = self.lock_level(growth)
        dominant = self.state.dominant_strategy
        margin = self.switch_edge_margin * (2.0 if lock == "strong" else 1.0 if lock == "consistent" else 0.0)

        offensive.sort(key=_intent_edge, reverse=True)
        top = offensive[0]

        if dominant and lock != "none":
            dominant_intents = [i for i in offensive if i.strategy_name == dominant]
            if dominant_intents:
                best_dom = max(dominant_intents, key=_intent_edge)
                if top.strategy_name != dominant:
                    gap = _intent_edge(top) - _intent_edge(best_dom)
                    if gap < margin:
                        offensive.remove(best_dom)
                        offensive.insert(0, best_dom)
                        notes.append(
                            f"Stickiness — keeping `{dominant}` ({lock} growth {growth:+.2%}, "
                            f"challenger `{top.strategy_name}` +{gap:+.4f} < {margin:+.4f} margin)"
                        )
                    else:
                        notes.append(
                            f"Strategy switch allowed — `{top.strategy_name}` beats `{dominant}` "
                            f"by {gap:+.4f} (margin {margin:+.4f})"
                        )

        elif self.exploration_mode(growth) and len(offensive) > 1:
            interval = max(1, round(1.0 / self.exploration_ratio)) if self.exploration_ratio > 0 else 999
            if self.state.total_trades > 0 and self.state.total_trades % interval == 0:
                alt = offensive[1]
                if _intent_edge(alt) >= _intent_edge(offensive[0]) * 0.85:
                    offensive[0], offensive[1] = offensive[1], offensive[0]
                    notes.append(
                        f"Exploration — trying `{alt.strategy_name}` "
                        f"({alt.from_asset}→{alt.to_asset}, flat growth {growth:+.2%})"
                    )

        if adaptive and lock != "strong":
            def _adaptive_rank(intent: TradeIntent) -> float:
                edge = _intent_edge(intent)
                if intent.strategy_name != dominant:
                    edge += 0.0003
                return edge

            offensive.sort(key=_adaptive_rank, reverse=True)

        reordered = defensive + offensive
        gov_status = GovernorStatus(
            dominant_strategy=dominant,
            growth_pct=growth,
            lock_level=lock,
            exploration_mode=self.exploration_mode(growth),
            notes=notes,
        )
        return reordered, gov_status, notes

    def record_trade(
        self,
        strategy_name: str,
        portfolio_value: float,
        gain_loss: float,
    ) -> None:
        stats = dict(self.state.strategy_stats)
        entry = dict(stats.get(strategy_name, {"trades": 0, "pnl": 0.0, "wins": 0}))
        entry["trades"] = int(entry.get("trades", 0)) + 1
        entry["pnl"] = float(entry.get("pnl", 0.0)) + gain_loss
        if gain_loss > 0:
            entry["wins"] = int(entry.get("wins", 0)) + 1
        stats[strategy_name] = entry
        self.state.strategy_stats = stats

        prev = self.state.dominant_strategy
        self.state.total_trades = int(getattr(self.state, "total_trades", 0)) + 1

        if prev != strategy_name:
            self.state.dominant_strategy = strategy_name
            self.state.dominant_since = self._now().isoformat()
            self._reset_growth_window(portfolio_value)
        elif not self.state.dominant_since:
            self.state.dominant_since = self._now().isoformat()

        self._save()

    def strategy_summary(self) -> str:
        dominant = self.state.dominant_strategy
        growth = self.growth_pct()
        lock = self.lock_level(growth)
        parts = []
        if dominant:
            since = self.state.dominant_since or "unknown"
            parts.append(f"**Dominant:** `{dominant}` since {since[:16]}")
        parts.append(f"**Growth ({self.growth_window_hours:.0f}h):** {growth:+.2%} ({lock})")
        stats = self.state.strategy_stats or {}
        if stats:
            ranked = sorted(
                stats.items(),
                key=lambda kv: float(kv[1].get("pnl", 0.0)),
                reverse=True,
            )
            lines = []
            for name, s in ranked[:4]:
                trades = int(s.get("trades", 0))
                pnl = float(s.get("pnl", 0.0))
                wins = int(s.get("wins", 0))
                lines.append(f"• `{name}` — {trades} trades, ${pnl:+.2f}, {wins}W")
            parts.append("**Strategy PnL (attributed):**\n" + "\n".join(lines))
        return "\n".join(parts)
