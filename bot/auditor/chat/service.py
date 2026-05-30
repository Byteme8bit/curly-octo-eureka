"""ChatService — orchestrates the LLM <-> tool loop for Auditor chat.

Two entry points:

- ``ask(question)``    : single-turn, no memory. Fresh system prompt each call.
- ``chat(channel_id, message)``  : multi-turn. Rolling per-channel history.

Both internally run the same loop:

    1. Compose conversation (system + history + new user message).
    2. Send to ``LLMBackend.complete(...)`` with the full read-only tool set.
    3. If the reply contains ``tool_calls``, execute each, append the results
       to the conversation, and loop. Hard-capped by ``max_tool_iterations``
       so a misbehaving LLM can't pin the audit thread.
    4. Return the final text reply.

The service is thread-safe (each ``chat`` call grabs its channel lock) so
Discord message dispatching can be parallelised later.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Sequence

from bot.auditor.chat.backends import LLMBackend, LLMMessage, LLMReply, ToolCall
from bot.auditor.chat.tools import Tool, ToolRegistry

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are the Auditor for an ETH paper-trading bot called TradeBot. \
You also see WatchDog's health reports. You answer the user's questions about what \
the bot is doing, why, and how it's performing.

CRITICAL RULES:
- ALWAYS respond with visible text. Even if the answer is "I don't know" or "I \
can't tell from available tools", say so explicitly. Never finish a turn with \
no text and no tool call — that leaves the user staring at nothing.
- You are STRICTLY READ-ONLY. You never execute trades, never write to disk, never \
restart the bot. Even if asked, refuse and explain that the user must use \
`Auditor -confirm <id>` for proposals or `TradeBot -` / `WatchDog -` commands for \
control actions.
- BE EFFICIENT WITH TOOL CALLS. The free-tier API has tight per-day caps. Plan \
which tools you need BEFORE calling any. Call multiple tools in a single turn when \
possible, never the same tool twice with identical arguments, and never call a tool \
"just to double-check" — trust the first answer.
- If the user's question is general (greetings, definitions, how-to about commands), \
answer directly with NO tool calls.
- Use tools only to look up live state instead of guessing. If a tool returns an \
error or empty data, say so plainly — do not fabricate values.
- This is a PAPER trading bot — no real money. Don't add disclaimers about \
financial advice; the user knows.
- Keep replies concise: ≤ 6 short sentences or a brief bullet list. The user is \
reading in Discord.
- When you cite numbers, mention the tool you got them from (e.g. \
"per get_portfolio_snapshot: ETH balance is 1.23"). It helps the user verify."""


@dataclass
class ChatTurn:
    """A persisted user/assistant exchange (tool calls + results stay in-thread, not stored)."""

    role: str  # 'user' | 'assistant'
    content: str


@dataclass
class ChatResult:
    text: str
    iterations: int = 0          # how many LLM round trips
    tool_calls_made: int = 0
    finish_reason: str = "stop"
    error: bool = False


@dataclass
class _ChannelState:
    history: list[ChatTurn] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)


class ChatService:
    """Orchestrate Q&A with optional multi-turn memory per Discord channel."""

    def __init__(
        self,
        *,
        backend: LLMBackend,
        tools: ToolRegistry,
        system_prompt: str = SYSTEM_PROMPT,
        max_turns: int = 6,
        max_tool_iterations: int = 2,
        temperature: float = 0.3,
        max_output_tokens: int = 1000,
        tool_result_max_chars: int = 2000,
    ) -> None:
        self.backend = backend
        self.tools = tools
        self.system_prompt = system_prompt
        self.max_turns = max(1, max_turns)
        self.max_tool_iterations = max(1, max_tool_iterations)
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.tool_result_max_chars = max(200, tool_result_max_chars)
        # ``OrderedDict`` so we could LRU-evict channels later if memory grows.
        self._channels: "OrderedDict[str, _ChannelState]" = OrderedDict()
        self._channels_lock = threading.Lock()

    # ----------------------------------------------------- public surface

    def ask(self, question: str) -> ChatResult:
        """Single-turn answer; conversation history is NOT updated."""
        question = (question or "").strip()
        if not question:
            return ChatResult(text="Ask me a question first — e.g. `Auditor -ask How is ETH doing today?`")
        messages = [
            LLMMessage(role="system", content=self.system_prompt),
            LLMMessage(role="user", content=question),
        ]
        return self._run_loop(messages)

    def chat(self, channel_id: str, message: str) -> ChatResult:
        """Multi-turn answer; appends both sides to the per-channel history."""
        message = (message or "").strip()
        if not message:
            return ChatResult(text="Send a message first — e.g. `Auditor -chat What were our worst trades this week?`")
        state = self._get_channel(channel_id)
        with state.lock:
            messages: list[LLMMessage] = [LLMMessage(role="system", content=self.system_prompt)]
            for turn in state.history:
                messages.append(LLMMessage(role=turn.role, content=turn.content))
            messages.append(LLMMessage(role="user", content=message))
            result = self._run_loop(messages)
            if not result.error and result.text:
                state.history.append(ChatTurn(role="user", content=message))
                state.history.append(ChatTurn(role="assistant", content=result.text))
                self._truncate_history(state)
            return result

    def clear(self, channel_id: str | None = None) -> int:
        """Reset history for one channel (or all when channel_id is None). Returns # cleared."""
        with self._channels_lock:
            if channel_id is None:
                count = sum(len(s.history) for s in self._channels.values())
                self._channels.clear()
                return count
            state = self._channels.pop(channel_id, None)
            return len(state.history) if state else 0

    def history_summary(self) -> dict:
        """For `Auditor -chatstatus`: per-channel turn counts."""
        with self._channels_lock:
            return {
                cid: len(state.history) // 2  # one "turn" = user + assistant pair
                for cid, state in self._channels.items()
            }

    # ----------------------------------------------------- internals

    def _get_channel(self, channel_id: str) -> _ChannelState:
        with self._channels_lock:
            state = self._channels.get(channel_id)
            if state is None:
                state = _ChannelState()
                self._channels[channel_id] = state
            else:
                self._channels.move_to_end(channel_id)
            return state

    def _truncate_history(self, state: _ChannelState) -> None:
        max_messages = self.max_turns * 2
        if len(state.history) > max_messages:
            del state.history[: len(state.history) - max_messages]

    def _run_loop(self, messages: list[LLMMessage]) -> ChatResult:
        tools_list: Sequence[Tool] = list(self.tools)
        iterations = 0
        tool_calls_made = 0
        last_text = ""
        last_finish = "stop"
        # Cache identical tool invocations within a single chat turn so the LLM
        # asking for `get_portfolio_snapshot` three times in a row costs us
        # only one execution AND one cached JSON blob (saved API tokens).
        # Key: (tool_name, json-stable-args). Value: serialised JSON payload.
        per_turn_cache: dict[tuple[str, str], str] = {}

        for _ in range(self.max_tool_iterations):
            iterations += 1
            try:
                reply: LLMReply = self.backend.complete(
                    messages,
                    tools=tools_list or None,
                    temperature=self.temperature,
                    max_output_tokens=self.max_output_tokens,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("LLM backend raised in _run_loop")
                return ChatResult(
                    text=f"Chat backend error: {exc}",
                    iterations=iterations,
                    tool_calls_made=tool_calls_made,
                    error=True,
                )

            last_text = reply.text or last_text
            last_finish = reply.finish_reason or last_finish

            if not reply.tool_calls:
                # Pure text reply — terminal.
                return ChatResult(
                    text=last_text or "(no reply text)",
                    iterations=iterations,
                    tool_calls_made=tool_calls_made,
                    finish_reason=last_finish,
                    error=(last_finish == "error"),
                )

            # Echo the assistant's tool-call request back into the conversation
            # so the backend can match function responses.
            messages.append(
                LLMMessage(
                    role="assistant",
                    content=reply.text or "",
                    tool_calls=list(reply.tool_calls),
                )
            )
            for call in reply.tool_calls:
                tool_calls_made += 1
                cache_key = (call.name, _stable_args_key(call.arguments))
                cached = per_turn_cache.get(cache_key)
                if cached is not None:
                    logger.debug("Reusing cached result for %s", call.name)
                    payload_json = cached
                else:
                    payload = self._invoke_tool(call)
                    payload_json = json.dumps(payload, default=str)
                    if len(payload_json) > self.tool_result_max_chars:
                        payload_json = (
                            payload_json[: self.tool_result_max_chars]
                            + '..."(truncated)"'
                        )
                    per_turn_cache[cache_key] = payload_json
                messages.append(
                    LLMMessage(
                        role="tool",
                        name=call.name,
                        content=payload_json,
                        tool_call_id=call.call_id,
                    )
                )

        return ChatResult(
            text=(
                last_text
                or "I needed more tool calls than allowed to answer that — "
                   "rephrase the question more narrowly?"
            ),
            iterations=iterations,
            tool_calls_made=tool_calls_made,
            finish_reason="length",
            error=False,
        )

    def _invoke_tool(self, call: ToolCall):
        tool = self.tools.find(call.name)
        if tool is None:
            logger.warning("LLM requested unknown tool %s", call.name)
            return {"error": f"unknown tool {call.name}"}
        return tool.invoke(call.arguments)


def _stable_args_key(args) -> str:
    """JSON-stable hash of tool arguments for per-turn caching."""
    if not args:
        return ""
    try:
        return json.dumps(args, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001
        return repr(args)
