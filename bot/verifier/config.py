"""Verifier settings — loaded from env with sensible defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from config import ROOT, load_settings


@dataclass(frozen=True)
class VerifierSettings:
    bot_root: Path
    state_file: Path
    paper_portfolio_file: Path
    receipts_dir: Path
    log_dir: Path
    runtime_log: Path
    reports_dir: Path

    min_eth_reserve: float
    max_alt_allocation_pct: float
    min_usd_trade: float
    fee_rate: float
    slippage_buffer_pct: float
    min_net_profit_pct: float
    min_trade_edge: float

    price_tolerance_pct: float
    slippage_assume_pct: float
    fee_tolerance_rel: float
    liquidity_volume_warn_ratio: float
    log_time_window_minutes: int

    skip_kraken: bool
    kraken_timeout_ms: int

    @classmethod
    def from_env(cls, *, bot_root: Path | None = None) -> VerifierSettings:
        root = bot_root or ROOT
        settings = load_settings()
        return cls(
            bot_root=root,
            state_file=settings.state_file,
            paper_portfolio_file=settings.paper_portfolio_file,
            receipts_dir=settings.receipts_dir,
            log_dir=settings.log_dir,
            runtime_log=settings.log_dir / "runtime.log",
            reports_dir=root / "reports",
            min_eth_reserve=settings.min_eth_reserve,
            max_alt_allocation_pct=settings.max_alt_allocation_pct,
            min_usd_trade=settings.min_usd_trade,
            fee_rate=settings.fee_rate,
            slippage_buffer_pct=settings.slippage_buffer_pct,
            min_net_profit_pct=settings.min_net_profit_pct,
            min_trade_edge=settings.min_trade_edge,
            price_tolerance_pct=float(os.getenv("VERIFIER_PRICE_TOLERANCE_PCT", "0.02")),
            slippage_assume_pct=float(os.getenv("VERIFIER_SLIPPAGE_ASSUME_PCT", "0.005")),
            fee_tolerance_rel=float(os.getenv("VERIFIER_FEE_TOLERANCE_REL", "0.15")),
            liquidity_volume_warn_ratio=float(os.getenv("VERIFIER_LIQUIDITY_WARN_RATIO", "0.01")),
            log_time_window_minutes=int(os.getenv("VERIFIER_LOG_WINDOW_MINUTES", "30")),
            skip_kraken=os.getenv("VERIFIER_SKIP_KRAKEN", "0") == "1",
            kraken_timeout_ms=settings.kraken_request_timeout_ms,
        )
