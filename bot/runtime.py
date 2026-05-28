import threading
from dataclasses import dataclass, field

from bot.status import StatusSnapshot


@dataclass
class TickSnapshot:
    portfolio: float = 0.0
    baseline_pnl: float = 0.0
    drawdown: float = 0.0
    holdings: dict[str, float] = field(default_factory=dict)
    usd_prices: dict[str, float] = field(default_factory=dict)
    status: StatusSnapshot | None = None
    trades: list[dict] = field(default_factory=list)
    status_since: str | None = None
    updated_at: str = ""


class BotRuntime:
    """Thread-safe runtime flags and latest tick snapshot for Discord commands."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.trading_active = True
        self.shutdown_requested = False
        self.snapshot = TickSnapshot()

    def set_trading_active(self, active: bool) -> None:
        with self._lock:
            self.trading_active = active

    def is_trading_active(self) -> bool:
        with self._lock:
            return self.trading_active

    def request_shutdown(self) -> None:
        with self._lock:
            self.shutdown_requested = True

    def should_shutdown(self) -> bool:
        with self._lock:
            return self.shutdown_requested

    def update_snapshot(self, snapshot: TickSnapshot) -> None:
        with self._lock:
            self.snapshot = snapshot

    def get_snapshot(self) -> TickSnapshot:
        with self._lock:
            return self.snapshot
