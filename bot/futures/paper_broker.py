"""Paper simulation for Kraken perpetual futures."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class FuturesPosition:
    symbol: str
    side: str  # "long" | "short"
    contracts: float
    entry_price: float
    leverage: float
    margin_usd: float
    opened_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "FuturesPosition":
        return cls(
            symbol=str(data["symbol"]),
            side=str(data["side"]),
            contracts=float(data["contracts"]),
            entry_price=float(data["entry_price"]),
            leverage=float(data["leverage"]),
            margin_usd=float(data["margin_usd"]),
            opened_at=str(data.get("opened_at") or ""),
        )


@dataclass
class FuturesPaperState:
    balance_usd: float
    positions: dict[str, FuturesPosition] = field(default_factory=dict)
    trades: list[dict] = field(default_factory=list)
    peak_equity: float = 0.0
    halted: bool = False
    halt_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "balance_usd": self.balance_usd,
            "positions": {k: v.to_dict() for k, v in self.positions.items()},
            "trades": self.trades,
            "peak_equity": self.peak_equity,
            "halted": self.halted,
            "halt_reason": self.halt_reason,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "FuturesPaperState":
        if not data:
            return cls(balance_usd=0.0)
        positions = {
            k: FuturesPosition.from_dict(v)
            for k, v in (data.get("positions") or {}).items()
        }
        return cls(
            balance_usd=float(data.get("balance_usd", 0.0)),
            positions=positions,
            trades=list(data.get("trades") or []),
            peak_equity=float(data.get("peak_equity", 0.0)),
            halted=bool(data.get("halted", False)),
            halt_reason=str(data.get("halt_reason") or ""),
        )


class FuturesPaperBroker:
    """Simulated perp wallet with leverage caps and drawdown halt."""

    def __init__(
        self,
        state_file: Path,
        *,
        initial_balance_usd: float = 1000.0,
        max_leverage: float = 5.0,
        max_position_usd: float = 100.0,
        drawdown_halt_pct: float = 0.10,
        fee_rate: float = 0.0005,
        reset: bool = False,
    ):
        self.state_file = state_file
        self.max_leverage = max(1.0, max_leverage)
        self.max_position_usd = max_position_usd
        self.drawdown_halt_pct = drawdown_halt_pct
        self.fee_rate = fee_rate
        self.state = self._load_or_create(initial_balance_usd, reset)

    def _load_or_create(self, initial_balance: float, reset: bool) -> FuturesPaperState:
        if reset and self.state_file.exists():
            self.state_file.unlink()
        if self.state_file.exists():
            with open(self.state_file, encoding="utf-8") as f:
                return FuturesPaperState.from_dict(json.load(f))
        state = FuturesPaperState(balance_usd=initial_balance, peak_equity=initial_balance)
        self.save(state)
        return state

    def save(self, state: FuturesPaperState | None = None) -> None:
        target = state or self.state
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(target.to_dict(), f, indent=2)

    def halt(self, reason: str) -> None:
        self.state.halted = True
        self.state.halt_reason = reason
        self.save()
        logger.error("FUTURES PAPER HALT: %s", reason)

    def equity(self, mark_prices: dict[str, float]) -> float:
        total = self.state.balance_usd
        for pos in self.state.positions.values():
            mark = mark_prices.get(pos.symbol, pos.entry_price)
            if pos.side == "long":
                pnl = (mark - pos.entry_price) * pos.contracts
            else:
                pnl = (pos.entry_price - mark) * pos.contracts
            total += pos.margin_usd + pnl
        return total

    def _update_peak_and_halt(self, mark_prices: dict[str, float]) -> None:
        eq = self.equity(mark_prices)
        if self.state.peak_equity <= 0:
            self.state.peak_equity = eq
        elif eq > self.state.peak_equity:
            self.state.peak_equity = eq
        if self.state.peak_equity > 0:
            dd = (self.state.peak_equity - eq) / self.state.peak_equity
            if dd >= self.drawdown_halt_pct and not self.state.halted:
                self.halt(
                    f"Futures drawdown {dd:.1%} >= {self.drawdown_halt_pct:.0%} limit"
                )

    def open_position(
        self,
        symbol: str,
        side: str,
        price: float,
        *,
        leverage: float,
        margin_usd: float,
        reason: str = "",
    ) -> dict | None:
        if self.state.halted or price <= 0 or margin_usd <= 0:
            return None
        if symbol in self.state.positions:
            return None
        lev = min(leverage, self.max_leverage)
        notional = margin_usd * lev
        if notional > self.max_position_usd:
            margin_usd = self.max_position_usd / lev
            notional = self.max_position_usd
        if margin_usd > self.state.balance_usd:
            return None
        fee = notional * self.fee_rate
        if margin_usd + fee > self.state.balance_usd:
            return None
        contracts = notional / price
        self.state.balance_usd -= margin_usd + fee
        now = datetime.now(timezone.utc).isoformat()
        self.state.positions[symbol] = FuturesPosition(
            symbol=symbol,
            side=side,
            contracts=contracts,
            entry_price=price,
            leverage=lev,
            margin_usd=margin_usd,
            opened_at=now,
        )
        trade = {
            "time": now,
            "action": "open",
            "symbol": symbol,
            "side": side,
            "contracts": contracts,
            "price": price,
            "margin_usd": margin_usd,
            "leverage": lev,
            "fee_usd": fee,
            "reason": reason,
            "paper": True,
        }
        self.state.trades.append(trade)
        self.save()
        return trade

    def close_position(
        self,
        symbol: str,
        price: float,
        *,
        reason: str = "",
    ) -> dict | None:
        pos = self.state.positions.get(symbol)
        if not pos or price <= 0:
            return None
        if pos.side == "long":
            pnl = (price - pos.entry_price) * pos.contracts
        else:
            pnl = (pos.entry_price - price) * pos.contracts
        notional = pos.contracts * price
        fee = notional * self.fee_rate
        self.state.balance_usd += pos.margin_usd + pnl - fee
        now = datetime.now(timezone.utc).isoformat()
        trade = {
            "time": now,
            "action": "close",
            "symbol": symbol,
            "side": pos.side,
            "contracts": pos.contracts,
            "price": price,
            "pnl_usd": pnl - fee,
            "fee_usd": fee,
            "reason": reason,
            "paper": True,
        }
        del self.state.positions[symbol]
        self.state.trades.append(trade)
        self.save()
        return trade

    def mark_to_market(self, mark_prices: dict[str, float]) -> None:
        self._update_peak_and_halt(mark_prices)
