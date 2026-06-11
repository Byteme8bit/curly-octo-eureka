"""Orchestrate independent verification of paper trades."""

from __future__ import annotations

from datetime import datetime, timezone

from bot.local_time import pacific_now
from bot.verifier.checks import (
    check_correlation,
    check_fee_realism,
    check_liquidity,
    check_market_reality,
    check_multi_hop,
    check_preflight,
    check_price_plausibility,
    check_size_constraints,
)
from bot.verifier.config import VerifierSettings
from bot.verifier.kraken import PublicKraken
from bot.verifier.models import SessionReport, TradeVerdict, Verdict
from bot.verifier.parsers import (
    estimate_trade_usd,
    infer_initial_balances,
    load_initial_balances,
    load_trades,
    receipt_path_for_trade,
    replay_balances_before,
)


def _aggregate_verdict(checks: list) -> Verdict:
    if any(c.verdict == Verdict.DENY for c in checks):
        return Verdict.DENY
    if any(c.verdict == Verdict.UNCERTAIN for c in checks):
        return Verdict.UNCERTAIN
    return Verdict.CONFIRM


def _filter_trades(
    trades: list[dict],
    *,
    last: int | None,
    since: str | None,
) -> list[tuple[int, dict]]:
    indexed = list(enumerate(trades))
    if since:
        since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        if since_dt.tzinfo is None:
            since_dt = since_dt.replace(tzinfo=timezone.utc)
        indexed = [
            (i, t)
            for i, t in indexed
            if datetime.fromisoformat(t["time"].replace("Z", "+00:00")) >= since_dt
        ]
    if last is not None and last > 0:
        indexed = indexed[-last:]
    return indexed


class Verifier:
    def __init__(self, settings: VerifierSettings | None = None):
        self.settings = settings or VerifierSettings.from_env()
        self._kraken: PublicKraken | None = None
        if not self.settings.skip_kraken:
            self._kraken = PublicKraken(timeout_ms=self.settings.kraken_timeout_ms)

    def verify_trade(
        self,
        trade: dict,
        trade_index: int,
        *,
        all_trades: list[dict],
        initial_balances: dict[str, float],
        usd_prices: dict[str, float] | None = None,
    ) -> TradeVerdict:
        balances_before = replay_balances_before(all_trades, trade_index, initial_balances)
        checks = [
            check_correlation(trade, self.settings),
            check_market_reality(trade, self._kraken),
            check_price_plausibility(trade, self._kraken, self.settings),
            check_fee_realism(trade, self._kraken, self.settings),
            check_size_constraints(
                trade,
                self.settings,
                balances_before=balances_before,
                usd_prices=usd_prices,
            ),
            check_multi_hop(trade),
            check_preflight(trade, self._kraken, self.settings),
            check_liquidity(trade, self._kraken, self.settings, usd_prices=usd_prices),
        ]
        receipt = receipt_path_for_trade(trade, self.settings.receipts_dir)
        return TradeVerdict(
            trade_index=trade_index,
            time=trade.get("time", ""),
            from_asset=trade.get("from_asset", ""),
            to_asset=trade.get("to_asset", ""),
            symbol=trade.get("symbol", ""),
            reason=trade.get("reason", ""),
            verdict=_aggregate_verdict(checks),
            checks=checks,
            receipt_file=receipt.name if receipt else None,
            trade_usd=estimate_trade_usd(trade, usd_prices),
        )

    def run(
        self,
        *,
        last: int | None = None,
        since: str | None = None,
    ) -> SessionReport:
        all_trades = load_trades(self.settings.state_file)
        state_balances = load_initial_balances(self.settings.state_file)
        if all_trades and state_balances:
            initial = infer_initial_balances(state_balances, all_trades)
        else:
            from config import load_settings
            initial = dict(load_settings().initial_balances)

        usd_prices: dict[str, float] = {"USD": 1.0}
        if self._kraken:
            try:
                self._kraken.ensure_markets()
                for asset in set(state_balances.keys()):
                    if asset != "USD":
                        sym = f"{asset}/USD"
                        if self._kraken.symbol_exists(sym):
                            ticker = self._kraken.exchange.fetch_ticker(sym)
                            usd_prices[asset] = float(ticker["last"])
            except Exception:  # noqa: BLE001
                pass

        selected = _filter_trades(all_trades, last=last, since=since)
        verdicts: list[TradeVerdict] = []
        paper_pnl = 0.0
        fee_drag = 0.0

        for idx, trade in selected:
            verdict = self.verify_trade(
                trade,
                idx,
                all_trades=all_trades,
                initial_balances=initial,
                usd_prices=usd_prices,
            )
            verdicts.append(verdict)
            paper_pnl += float(trade.get("gain_loss", 0))
            fee_drag += float(trade.get("fee_usd", 0))

        counts = {v: 0 for v in Verdict}
        for v in verdicts:
            counts[v.verdict] += 1

        systematic: list[str] = []
        triangular = sum(
            1 for v in verdicts
            if any(c.name == "multi_hop_atomic" and c.verdict == Verdict.UNCERTAIN for c in v.checks)
        )
        if triangular:
            systematic.append(
                f"{triangular} trade(s) use triangular/multi-hop routes — live execution may fail mid-route"
            )
        missing_receipts = sum(1 for v in verdicts if v.verdict == Verdict.DENY and not v.receipt_file)
        if missing_receipts:
            systematic.append(f"{missing_receipts} trade(s) missing receipt correlation")
        preflight_fails = sum(
            1 for v in verdicts
            if any(c.name == "preflight" and c.verdict == Verdict.DENY for c in v.checks)
        )
        if preflight_fails:
            systematic.append(f"{preflight_fails} trade(s) would fail pre-flight on live Kraken fees")

        return SessionReport(
            generated_at=format_pacific_now(),
            trades_reviewed=len(verdicts),
            confirm=counts[Verdict.CONFIRM],
            deny=counts[Verdict.DENY],
            uncertain=counts[Verdict.UNCERTAIN],
            paper_pnl_usd=paper_pnl,
            estimated_fee_drag_usd=fee_drag,
            systematic_issues=systematic,
            trade_verdicts=verdicts,
            sources={
                "state_file": str(self.settings.state_file),
                "receipts_dir": str(self.settings.receipts_dir),
                "log_dir": str(self.settings.log_dir),
                "runtime_log": str(self.settings.runtime_log),
            },
        )


def format_pacific_now() -> str:
    return pacific_now().strftime("%Y-%m-%d %H:%M:%S PDT")


def verify_trades(
    *,
    last: int | None = None,
    since: str | None = None,
    settings: VerifierSettings | None = None,
) -> SessionReport:
    return Verifier(settings).run(last=last, since=since)
