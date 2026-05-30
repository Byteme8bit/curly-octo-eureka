"""Human-readable paper portfolio snapshot file.

The bot writes ``paper_portfolio.json`` on each tick (and on reset) with
holdings, USD values, and summary metrics. Startup banner and CLI tools
read this file for display.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from bot.local_time import format_pacific

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PaperPortfolioSnapshot:
    updated_at: str
    portfolio_usd: float
    baseline_pnl: float
    drawdown_pct: float
    holdings: dict[str, dict[str, float]]

    def balances(self) -> dict[str, float]:
        return {
            asset: float(row.get("qty", 0.0))
            for asset, row in self.holdings.items()
            if float(row.get("qty", 0.0)) > 0
        }

    def summary_line(self) -> str:
        return (
            f"Saved ${self.portfolio_usd:,.2f}  "
            f"(PnL {self.baseline_pnl:+.2f}, drawdown {self.drawdown_pct:.2%})  "
            f"@ {self.updated_at}"
        )


class PaperPortfolioLog:
    """Read/write ``paper_portfolio.json``."""

    def __init__(self, path: Path):
        self.path = path

    def write(
        self,
        *,
        holdings: dict[str, float],
        usd_prices: dict[str, float],
        portfolio_usd: float,
        baseline_pnl: float,
        drawdown_pct: float,
        updated_at: str | None = None,
    ) -> None:
        ts = updated_at or format_pacific()
        rows: dict[str, dict[str, float]] = {}
        for asset, qty in sorted(holdings.items()):
            if qty <= 0:
                continue
            price = 1.0 if asset == "USD" else float(usd_prices.get(asset, 0.0))
            rows[asset] = {
                "qty": round(qty, 8),
                "usd_price": round(price, 6),
                "usd_value": round(qty * price, 2),
            }

        payload = {
            "updated_at": ts,
            "portfolio_usd": round(portfolio_usd, 2),
            "baseline_pnl": round(baseline_pnl, 2),
            "drawdown_pct": round(drawdown_pct, 6),
            "holdings": rows,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def load(self) -> PaperPortfolioSnapshot | None:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("PaperPortfolioLog: portfolio file unreadable; skipping — %s", exc)
            return None
        holdings = data.get("holdings") or {}
        if not isinstance(holdings, dict):
            holdings = {}
        return PaperPortfolioSnapshot(
            updated_at=str(data.get("updated_at", "")),
            portfolio_usd=float(data.get("portfolio_usd", 0.0)),
            baseline_pnl=float(data.get("baseline_pnl", 0.0)),
            drawdown_pct=float(data.get("drawdown_pct", 0.0)),
            holdings={
                str(asset): {
                    "qty": float(row.get("qty", 0.0)),
                    "usd_price": float(row.get("usd_price", 0.0)),
                    "usd_value": float(row.get("usd_value", 0.0)),
                }
                for asset, row in holdings.items()
                if isinstance(row, dict)
            },
        )

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()

    def bootstrap_from_state(self, state_file: Path) -> PaperPortfolioSnapshot | None:
        """Build a snapshot from ``.paper_state.json`` when no tick file exists yet."""
        if not state_file.exists():
            return None
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "PaperPortfolioLog: paper state file unreadable; cannot bootstrap — %s", exc
            )
            return None

        balances = data.get("balances") or {}
        if not isinstance(balances, dict):
            return None

        risk = data.get("risk") or {}
        baseline = float(risk.get("baseline_portfolio", 0.0))
        peak = float(risk.get("peak_portfolio", 0.0))

        holdings: dict[str, dict[str, float]] = {}
        for asset, raw_qty in sorted(balances.items()):
            qty = float(raw_qty)
            if qty <= 0:
                continue
            holdings[str(asset)] = {
                "qty": round(qty, 8),
                "usd_price": 0.0,
                "usd_value": 0.0,
            }

        if not holdings:
            return None

        snap = PaperPortfolioSnapshot(
            updated_at=format_pacific() + " (from saved paper state)",
            portfolio_usd=0.0,
            baseline_pnl=0.0,
            drawdown_pct=0.0,
            holdings=holdings,
        )
        payload = {
            "updated_at": snap.updated_at,
            "portfolio_usd": snap.portfolio_usd,
            "baseline_pnl": snap.baseline_pnl,
            "drawdown_pct": snap.drawdown_pct,
            "holdings": snap.holdings,
            "source": "paper_state_bootstrap",
            "baseline_portfolio": baseline,
            "peak_portfolio": peak,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return snap

    def format_text(self, *, state_file: Path | None = None) -> str:
        snap = self.load()
        if not snap and state_file is not None:
            snap = self.bootstrap_from_state(state_file)
            if snap:
                body = self._format_snapshot(snap)
                return (
                    body
                    + "\n\n"
                    + "(Bootstrapped from .paper_state.json — quantities only. "
                    + "Start/restart the bot for live USD prices.)"
                )
        if not snap:
            hint = ""
            if state_file is not None:
                hint = f"\nNo saved paper state at {state_file} either."
            return f"No portfolio snapshot at {self.path}{hint}"
        return self._format_snapshot(snap)

    def _format_snapshot(self, snap: PaperPortfolioSnapshot) -> str:
        lines = [
            f"Paper portfolio — {self.path}",
            f"Updated:   {snap.updated_at}",
        ]
        if snap.portfolio_usd > 0:
            lines.extend([
                f"Total:     ${snap.portfolio_usd:,.2f}",
                f"PnL:       {snap.baseline_pnl:+.2f} from baseline",
                f"Drawdown:  {snap.drawdown_pct:.2%}",
            ])
        else:
            lines.append("Total:     (USD values pending — start bot for live prices)")
        lines.extend(["", "Holdings:"])
        for asset, row in sorted(snap.holdings.items(), key=lambda x: -x[1]["usd_value"]):
            if row["usd_price"] > 0:
                lines.append(
                    f"  {asset:6s}  {row['qty']:>12.4f}  "
                    f"@ ${row['usd_price']:>8.2f}  = ${row['usd_value']:>10.2f}"
                )
            else:
                lines.append(f"  {asset:6s}  {row['qty']:>12.4f}")
        return "\n".join(lines)
