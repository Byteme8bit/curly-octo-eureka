"""Parse trading-bot log lines, receipts, and paper state."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

PORTFOLIO_RE = re.compile(
    r"Portfolio:\s+\$([\d,]+\.\d+)\s+\(PnL\s+([+-][\d.]+)\s+\|\s+drawdown\s+([\d.]+)%\)"
)
TRADE_NARRATIVE_RE = re.compile(
    r"^\s*Traded\s+(.+?)\s+because\s+(.+)$", re.MULTILINE
)
TRADE_FEE_RE = re.compile(
    r"Fee:\s+\$([\d.]+)\s+\|\s+Gain/Loss:\s+(.+)$", re.MULTILINE
)
ERROR_LOG_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+\w+)\s+\[(ERROR|CRITICAL)\]\s+(.+)$"
)
CONTEXT_KEYWORDS = (
    "Decision:",
    "Traded ",
    "Risk gate:",
    "MARKET CHECK",
    "Considering:",
    "Adaptive",
    "Pre-flight",
    "Best ",
)
RECEIPT_GAIN_RE = re.compile(r"Gain/Loss:\s+([+-]?\$[\d.]+|\$[\d.]+)\s+\((\w+)\)")


@dataclass(frozen=True)
class LogErrorRecord:
    at: str
    level: str
    message: str
    context: str = ""


@dataclass(frozen=True)
class PortfolioSnapshot:
    portfolio: float
    pnl: float
    drawdown_pct: float
    raw_line: str


@dataclass(frozen=True)
class TradeEvent:
    narrative: str
    reason: str
    fee_usd: float
    gain_loss_label: str
    source: str  # "log" | "receipt"
    source_ref: str


def parse_portfolio_line(line: str) -> PortfolioSnapshot | None:
    match = PORTFOLIO_RE.search(line)
    if not match:
        return None
    portfolio = float(match.group(1).replace(",", ""))
    pnl = float(match.group(2))
    drawdown = float(match.group(3)) / 100.0
    return PortfolioSnapshot(
        portfolio=portfolio, pnl=pnl, drawdown_pct=drawdown, raw_line=line.strip()
    )


def parse_trade_block(text: str, *, source: str, source_ref: str) -> list[TradeEvent]:
    events: list[TradeEvent] = []
    narratives = list(TRADE_NARRATIVE_RE.finditer(text))
    fees = list(TRADE_FEE_RE.finditer(text))
    for idx, match in enumerate(narratives):
        fee_usd = 0.0
        gain_label = "unknown"
        if idx < len(fees):
            fee_usd = float(fees[idx].group(1))
            gain_label = fees[idx].group(2).strip()
        events.append(
            TradeEvent(
                narrative=f"Traded {match.group(1).strip()}",
                reason=match.group(2).strip(),
                fee_usd=fee_usd,
                gain_loss_label=gain_label,
                source=source,
                source_ref=source_ref,
            )
        )
    return events


def parse_receipt(path: Path) -> TradeEvent | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    trade_lines = [ln for ln in text.splitlines() if ln.startswith("Traded ")]
    if not trade_lines:
        return None
    narrative = trade_lines[0]
    reason = narrative.split(" because ", 1)[1] if " because " in narrative else ""
    fee_usd = 0.0
    gain_label = "unknown"
    fee_match = RECEIPT_GAIN_RE.search(text)
    if fee_match:
        gain_label = f"{fee_match.group(1)} ({fee_match.group(2)})"
    for line in text.splitlines():
        if line.startswith("Fee:"):
            try:
                fee_usd = float(line.split("$")[1].strip())
            except (IndexError, ValueError):
                pass
            break
    return TradeEvent(
        narrative=narrative,
        reason=reason,
        fee_usd=fee_usd,
        gain_loss_label=gain_label,
        source="receipt",
        source_ref=path.name,
    )


def parse_runtime_errors(text: str) -> list[LogErrorRecord]:
    errors: list[LogErrorRecord] = []
    for match in ERROR_LOG_RE.finditer(text):
        errors.append(
            LogErrorRecord(
                at=match.group(1),
                level=match.group(2),
                message=match.group(3).strip(),
            )
        )
    return errors


def extract_action_context(session_log_text: str, *, max_items: int = 8) -> str:
    """Recent bot actions/decisions from session log tail."""
    if not session_log_text:
        return "(no session log context)"
    picked: list[str] = []
    for line in reversed(session_log_text.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        if any(key in stripped for key in CONTEXT_KEYWORDS):
            picked.append(stripped[:200])
            if len(picked) >= max_items:
                break
    if not picked:
        tail = [ln.strip() for ln in session_log_text.splitlines() if ln.strip()][-5:]
        return "\n".join(tail) if tail else "(no context found)"
    picked.reverse()
    return "\n".join(picked)


def read_log_tail(path: Path, max_bytes: int = 120_000) -> str:
    if not path.exists():
        return ""
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def load_paper_state(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def pnl_milestone_band(pnl: float, baseline: float, threshold_pct: float) -> int:
    if baseline <= 0 or threshold_pct <= 0:
        return 0
    ratio = pnl / baseline
    if ratio >= threshold_pct:
        return int(ratio / threshold_pct)
    if ratio <= -threshold_pct:
        return -int(abs(ratio) / threshold_pct)
    return 0


def gain_usd_from_label(label: str) -> float:
    text = label.replace(",", "").lower()
    if "entry" in text or "break-even" in text:
        return 0.0
    for token in text.replace("(", " ").replace(")", " ").split():
        cleaned = token.lstrip("+").lstrip("$")
        if not cleaned.replace(".", "").isdigit():
            continue
        value = float(cleaned)
        if "loss" in text:
            return -value
        if "profit" in text or token.startswith("+") or text.strip().startswith("+"):
            return value
    return 0.0
