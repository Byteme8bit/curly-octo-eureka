"""Tests for Auditor conversational chat.

All tests use stub LLM backends; nothing in this file touches the real Gemini
SDK or makes a network call. The Gemini-specific helpers live in
``bot.auditor.chat.backends`` and are exercised in ``test_gemini_helpers``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Sequence

import pytest

from bot.auditor.chat.backends import LLMMessage, LLMReply, ToolCall
from bot.auditor.chat.service import ChatResult, ChatService
from bot.auditor.chat.tools import Tool, ToolRegistry, build_tool_registry


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


@dataclass
class _ScriptedBackend:
    """Returns a queued sequence of replies, recording every call for assertions."""

    replies: list[LLMReply]
    available: bool = True
    calls: list[Sequence[LLMMessage]] | None = None

    def __post_init__(self) -> None:
        self.calls = []

    def complete(
        self,
        messages,
        *,
        tools=None,
        temperature: float = 0.3,
        max_output_tokens: int = 1500,
    ) -> LLMReply:
        self.calls.append(list(messages))
        if not self.replies:
            return LLMReply(text="(scripted backend out of replies)", finish_reason="stop")
        return self.replies.pop(0)


def _make_broker(trades=None, balances=None):
    return SimpleNamespace(
        state=SimpleNamespace(
            trades=list(trades or []),
            balances=balances or {"ETH": 1.5, "USD": 250.0},
        ),
        risk=SimpleNamespace(peak_portfolio=2000.0),
    )


def _settings_stub():
    return SimpleNamespace(
        min_trade_edge=0.006,
        trade_size_pct=0.10,
        min_net_profit_pct=0.0005,
        fee_rate=0.0026,
        idle_reeval_hours=2.0,
        strategy_exploration_ratio=0.25,
        min_eth_reserve=0.25,
        max_alt_allocation_pct=0.40,
        watch_assets=("ETH", "BTC", "SOL"),
        usd_symbols=("ETH/USD",),
        candle_timeframe="5m",
        poll_interval=12,
        strategy_names=("cross_momentum",),
    )


def _make_registry(tmp_path, *, broker=None, trades=None):
    broker = broker or _make_broker(trades=trades)
    return build_tool_registry(
        broker=broker,
        settings=_settings_stub(),
        portfolio_log=None,
        overrides_file=tmp_path / "runtime_overrides.json",
        audit_state_provider=lambda: SimpleNamespace(pending_proposals={}),
        watchdog_state_provider=lambda: None,
        news_client_provider=lambda: None,
        reports_dir=tmp_path / "reports",
    )


# ---------------------------------------------------------------------------
# tool registry
# ---------------------------------------------------------------------------


def test_registry_exposes_expected_tools(tmp_path: Path) -> None:
    reg = _make_registry(tmp_path)
    names = set(reg.names())
    assert {
        "get_portfolio_snapshot",
        "get_recent_trades",
        "get_strategy_performance",
        "get_active_overrides",
        "get_pending_proposals",
        "get_last_audit_summary",
        "get_watchdog_health",
        "get_recent_errors",
        "get_recent_news",
        "get_bot_settings",
        "get_market_prices",
    } <= names


def test_get_portfolio_snapshot_returns_balances(tmp_path: Path) -> None:
    reg = _make_registry(tmp_path)
    tool = reg.find("get_portfolio_snapshot")
    out = tool.invoke({})
    assert "balances" in out
    assert out["balances"]["ETH"] == 1.5
    assert out["balances"]["USD"] == 250.0
    assert out["peak_portfolio_usd"] == 2000.0


def test_get_recent_trades_filters_by_asset(tmp_path: Path) -> None:
    trades = [
        {"strategy": "x", "from_asset": "USD", "to_asset": "ETH", "gain_loss": 0.0},
        {"strategy": "x", "from_asset": "ETH", "to_asset": "SOL", "gain_loss": 1.2},
        {"strategy": "x", "from_asset": "USD", "to_asset": "BTC", "gain_loss": -0.5},
    ]
    reg = _make_registry(tmp_path, trades=trades)
    tool = reg.find("get_recent_trades")
    out = tool.invoke({"asset": "ETH"})
    assert out["count"] == 2  # USD->ETH and ETH->SOL both touch ETH
    btc_only = tool.invoke({"asset": "BTC"})
    assert btc_only["count"] == 1


def test_get_strategy_performance_aggregates_wins_losses(tmp_path: Path) -> None:
    trades = [
        {"strategy": "alpha", "gain_loss": 1.0, "fee_usd": 0.1},
        {"strategy": "alpha", "gain_loss": 2.0, "fee_usd": 0.1},
        {"strategy": "alpha", "gain_loss": -1.5, "fee_usd": 0.1},
        {"strategy": "beta", "gain_loss": -0.3, "fee_usd": 0.05},
    ]
    reg = _make_registry(tmp_path, trades=trades)
    out = reg.find("get_strategy_performance").invoke({})
    assert out["by_strategy"]["alpha"]["wins"] == 2
    assert out["by_strategy"]["alpha"]["losses"] == 1
    assert out["by_strategy"]["alpha"]["total_pnl"] == pytest.approx(1.5)
    assert out["by_strategy"]["alpha"]["win_rate"] == pytest.approx(2 / 3)
    assert out["by_strategy"]["beta"]["losses"] == 1


def test_get_active_overrides_reads_runtime_file(tmp_path: Path) -> None:
    overrides = tmp_path / "runtime_overrides.json"
    overrides.write_text(json.dumps({"MIN_TRADE_EDGE": 0.012}), encoding="utf-8")
    reg = build_tool_registry(
        broker=_make_broker(),
        settings=_settings_stub(),
        overrides_file=overrides,
        audit_state_provider=lambda: SimpleNamespace(pending_proposals={}),
        reports_dir=tmp_path / "reports",
    )
    out = reg.find("get_active_overrides").invoke({})
    assert out["overrides"]["MIN_TRADE_EDGE"] == pytest.approx(0.012)


def test_get_last_audit_summary_finds_latest_file(tmp_path: Path) -> None:
    reports = tmp_path / "reports" / "2026-05-27"
    reports.mkdir(parents=True)
    older = reports / "audit-090000.md"
    newer = reports / "audit-150000.md"
    older.write_text("older audit", encoding="utf-8")
    newer.write_text("# newest audit body", encoding="utf-8")
    reg = build_tool_registry(
        broker=_make_broker(),
        settings=_settings_stub(),
        overrides_file=tmp_path / "runtime_overrides.json",
        audit_state_provider=lambda: SimpleNamespace(pending_proposals={}),
        reports_dir=tmp_path / "reports",
    )
    out = reg.find("get_last_audit_summary").invoke({})
    assert out["path"] is not None
    assert out["summary"] == "# newest audit body"


def test_get_recent_news_skips_when_client_missing(tmp_path: Path) -> None:
    reg = _make_registry(tmp_path)
    out = reg.find("get_recent_news").invoke({"limit": 3})
    assert out == {"headlines": [], "available": False}


def test_tool_invoke_swallows_handler_exceptions() -> None:
    def boom() -> dict:
        raise RuntimeError("oops")

    tool = Tool(name="boom", description="raises", parameters={"type": "object", "properties": {}}, handler=boom)
    out = tool.invoke({})
    assert "error" in out
    assert "oops" in out["error"]


# ---------------------------------------------------------------------------
# ChatService single-turn
# ---------------------------------------------------------------------------


def test_chat_service_ask_returns_text(tmp_path: Path) -> None:
    backend = _ScriptedBackend(replies=[LLMReply(text="Hello human.", finish_reason="stop")])
    service = ChatService(backend=backend, tools=_make_registry(tmp_path))
    result = service.ask("hi")
    assert result.text == "Hello human."
    assert result.iterations == 1
    assert result.tool_calls_made == 0
    assert not result.error


def test_chat_service_ask_with_empty_question_returns_help() -> None:
    backend = _ScriptedBackend(replies=[])
    service = ChatService(backend=backend, tools=ToolRegistry())
    result = service.ask("   ")
    assert "Ask me a question first" in result.text


def test_chat_service_executes_tool_call_then_synthesises_reply(tmp_path: Path) -> None:
    reg = _make_registry(tmp_path)
    backend = _ScriptedBackend(replies=[
        LLMReply(
            text="",
            tool_calls=[ToolCall(name="get_portfolio_snapshot", arguments={}, call_id="c1")],
            finish_reason="tool",
        ),
        LLMReply(text="You hold 1.5 ETH plus $250 cash.", finish_reason="stop"),
    ])
    service = ChatService(backend=backend, tools=reg)
    result = service.ask("How are we doing?")
    assert result.iterations == 2
    assert result.tool_calls_made == 1
    assert "1.5 ETH" in result.text


def test_chat_service_caps_tool_iterations(tmp_path: Path) -> None:
    reg = _make_registry(tmp_path)
    # Build a backend that keeps requesting tool calls forever.
    infinite_calls = [
        LLMReply(
            text="",
            tool_calls=[ToolCall(name="get_portfolio_snapshot", arguments={}, call_id=f"c{i}")],
            finish_reason="tool",
        )
        for i in range(10)
    ]
    backend = _ScriptedBackend(replies=infinite_calls)
    service = ChatService(backend=backend, tools=reg, max_tool_iterations=3)
    result = service.ask("loop please")
    assert result.iterations == 3
    assert result.finish_reason == "length"
    assert "needed more tool calls" in result.text or "(no reply" in result.text


# ---------------------------------------------------------------------------
# ChatService multi-turn memory
# ---------------------------------------------------------------------------


def test_chat_multi_turn_remembers_per_session(tmp_path: Path) -> None:
    backend = _ScriptedBackend(replies=[
        LLMReply(text="Hi there!", finish_reason="stop"),
        LLMReply(text="Yes, I remember.", finish_reason="stop"),
    ])
    service = ChatService(backend=backend, tools=_make_registry(tmp_path), max_turns=5)
    service.chat("user-A", "hi")
    service.chat("user-A", "do you remember me?")
    # Second call's messages should include the user/assistant pair from call 1.
    second_call = backend.calls[1]
    roles = [m.role for m in second_call]
    assert roles[0] == "system"
    assert roles[1:5] == ["user", "assistant", "user"]
    # Sanity check that the prior assistant text leaked into the history.
    assert any(m.role == "assistant" and "Hi there!" in m.content for m in second_call)


def test_chat_multi_turn_history_truncates_to_max_turns(tmp_path: Path) -> None:
    backend = _ScriptedBackend(replies=[
        LLMReply(text=f"reply-{i}", finish_reason="stop") for i in range(6)
    ])
    service = ChatService(backend=backend, tools=_make_registry(tmp_path), max_turns=2)
    for i in range(6):
        service.chat("user-B", f"q{i}")
    # max_turns=2 means we keep 4 messages (2 user + 2 assistant).
    last_call = backend.calls[-1]
    user_msgs = [m for m in last_call if m.role == "user"]
    assistant_msgs = [m for m in last_call if m.role == "assistant"]
    assert len(user_msgs) <= 3  # 2 retained + the newly-sent one
    assert len(assistant_msgs) <= 2


def test_chat_clear_wipes_session_history(tmp_path: Path) -> None:
    backend = _ScriptedBackend(replies=[
        LLMReply(text="one", finish_reason="stop"),
        LLMReply(text="two", finish_reason="stop"),
    ])
    service = ChatService(backend=backend, tools=_make_registry(tmp_path))
    service.chat("user-C", "ping")
    cleared = service.clear("user-C")
    assert cleared == 2  # user + assistant
    # Subsequent message should start fresh — only system + new user in the request.
    service.chat("user-C", "ping again")
    last_call = backend.calls[-1]
    roles = [m.role for m in last_call]
    assert roles == ["system", "user"]


def test_chat_history_summary_counts_turns(tmp_path: Path) -> None:
    backend = _ScriptedBackend(replies=[
        LLMReply(text=f"r{i}", finish_reason="stop") for i in range(4)
    ])
    service = ChatService(backend=backend, tools=_make_registry(tmp_path))
    service.chat("u1", "q1")
    service.chat("u1", "q2")
    service.chat("u2", "q3")
    summary = service.history_summary()
    assert summary == {"u1": 2, "u2": 1}


# ---------------------------------------------------------------------------
# Backend error handling
# ---------------------------------------------------------------------------


class _RaisingBackend:
    available = True

    def complete(self, *args, **kwargs):
        raise RuntimeError("backend down")


def test_chat_service_returns_graceful_error_when_backend_raises(tmp_path: Path) -> None:
    service = ChatService(backend=_RaisingBackend(), tools=_make_registry(tmp_path))
    result = service.ask("hi")
    assert result.error is True
    assert "backend down" in result.text


# ---------------------------------------------------------------------------
# Integration via AuditorService — chat disabled / lazy init
# ---------------------------------------------------------------------------


def _auditor_service_with_chat(tmp_path: Path, **chat_overrides):
    from bot.auditor.config import AuditorConfig
    from bot.auditor_service import AuditorService

    cfg = AuditorConfig(
        enabled=True,
        daily_run_hour_pacific=8,
        trade_count_trigger=20,
        pnl_pct_trigger=0.05,
        news_enabled=False,
        news_provider="rss",
        cryptopanic_api_key="",
        rss_feeds="",
        news_max_items=5,
        proposals_ttl_minutes=60,
        reports_dir=tmp_path / "reports",
        state_file=tmp_path / ".auditor_state.json",
        **{
            "chat_enabled": True,
            "chat_backend": "null",
            "chat_model": "test",
            "chat_api_key": "",
            "chat_max_turns": 3,
            "chat_max_tokens": 200,
            "chat_temperature": 0.0,
            "chat_tool_iterations": 2,
            **chat_overrides,
        },
    )
    return AuditorService(
        _settings_stub(),
        cfg,
        broker=_make_broker(),
        discord=None,
        overrides_file=tmp_path / "runtime_overrides.json",
    )


def test_auditor_service_ask_when_chat_disabled_returns_helpful_message(tmp_path: Path) -> None:
    service = _auditor_service_with_chat(tmp_path, chat_enabled=False)
    reply = service.ask("anything")
    assert "disabled" in reply.lower()
    assert "GEMINI_API_KEY" in reply


def test_auditor_service_ask_uses_null_backend_when_configured(tmp_path: Path) -> None:
    service = _auditor_service_with_chat(tmp_path)
    reply = service.ask("hello")
    # Null backend returns the canned 'disabled' reason
    assert "disabled" in reply.lower()


def test_auditor_service_chat_status_reports_enabled_and_backend(tmp_path: Path) -> None:
    service = _auditor_service_with_chat(tmp_path)
    status = service.chat_status()
    assert "enabled" in status.lower()
    assert "null" in status
    assert "test" in status  # the configured model name


# ---------------------------------------------------------------------------
# Regression: every AuditorConfig field must be wired from Settings in engine.py
# ---------------------------------------------------------------------------


def test_settings_to_auditor_config_wiring_is_complete() -> None:
    """Catches the class of bug where a new AuditorConfig field is added but
    `bot/engine.py` forgets to pass it through from Settings. We literally
    parse engine.py looking for `<field>=settings.auditor_<field>` per field.
    """
    import inspect
    from pathlib import Path

    from bot.auditor.config import AuditorConfig

    engine_src = (
        Path(__file__).resolve().parent.parent / "bot" / "engine.py"
    ).read_text(encoding="utf-8")

    # AuditorConfig fields that intentionally aren't sourced from Settings.
    SKIP = {
        "reports_dir",      # built from settings.auditor_reports_dir directly
        "state_file",       # built from settings.auditor_state_file directly
    }
    expected = [
        name for name in inspect.signature(AuditorConfig).parameters
        if name not in SKIP
    ]
    missing = [
        name for name in expected
        if f"{name}=settings.auditor_{name}" not in engine_src
    ]
    assert not missing, (
        "engine.py does not pass these AuditorConfig fields through from Settings:\n  "
        + "\n  ".join(missing)
        + "\nAdd lines like `<field>=settings.auditor_<field>,` to the AuditorConfig "
          "construction in TradingEngine.__init__."
    )
