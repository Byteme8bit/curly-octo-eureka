from dataclasses import dataclass

from bot.strategies.base import RotationOption, StrategyResult


@dataclass
class StatusSnapshot:
    mode: str  # "trade" | "hold" | "paused"
    summary_key: str
    idle_reason: str
    considering: list[str]


def _format_option(op: RotationOption) -> str:
    net = op.edge - op.required_edge
    if net >= 0:
        tag = "ready if approved"
    else:
        tag = f"need {op.required_edge - op.edge:+.4f} more edge"
    path = op.path.replace("->", " -> ") if op.path else ""
    path_note = f" via {path}" if path else ""
    return f"{op.from_asset} -> {op.to_asset} ({op.category}) — {tag}{path_note}"


def _option_coarse_key(op: RotationOption) -> str:
    net = op.edge - op.required_edge
    state = "ready" if net >= 0 else "below"
    return f"{op.from_asset}->{op.to_asset}:{op.category}:{state}"


def build_status_snapshot(
    result: StrategyResult,
    trades: list[dict],
    blocked: list[str],
    *,
    is_paused: bool,
    pause_message: str = "",
) -> StatusSnapshot:
    if trades:
        trade_bits = [
            f"{t['from_asset']}->{t['to_asset']}" for t in trades
        ]
        return StatusSnapshot(
            mode="trade",
            summary_key="trade:" + ",".join(trade_bits),
            idle_reason="",
            considering=[],
        )

    if is_paused:
        return StatusSnapshot(
            mode="paused",
            summary_key=f"paused:{pause_message}",
            idle_reason=pause_message,
            considering=[],
        )

    ranked_ops = sorted(
        result.opportunities,
        key=lambda o: o.edge - o.required_edge,
        reverse=True,
    )
    seen: set[str] = set()
    considering: list[str] = []
    coarse_keys: list[str] = []
    for op in ranked_ops:
        key = f"{op.from_asset}->{op.to_asset}:{op.category}"
        if key in seen:
            continue
        seen.add(key)
        considering.append(_format_option(op))
        coarse_keys.append(_option_coarse_key(op))
        if len(considering) >= 5:
            break

    for intent in result.intents:
        line = f"Pending: {intent.from_asset} -> {intent.to_asset}"
        coarse = f"pending:{intent.from_asset}->{intent.to_asset}"
        if coarse not in coarse_keys:
            considering.insert(0, line)
            coarse_keys.insert(0, coarse)

    extra_blocked = [n for n in blocked if n != result.idle_reason][:3]
    key_parts = coarse_keys + extra_blocked
    if is_paused:
        key_parts.append(f"paused:{pause_message}")
    elif not considering and not extra_blocked:
        key_parts.append("hold:watching")

    summary_key = "|".join(key_parts)

    return StatusSnapshot(
        mode="hold",
        summary_key=summary_key,
        idle_reason=result.idle_reason,
        considering=considering,
    )
