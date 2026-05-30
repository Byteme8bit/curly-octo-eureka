"""LLM backend abstraction + the Gemini implementation.

The Auditor chat layer talks to the LLM through a small, provider-agnostic
interface so we can add Anthropic/OpenAI later without touching the service
or the tool registry. Only Gemini is implemented today (matches the user's
existing Google subscription).

The Gemini SDK (``google-genai``) is **lazy-imported** so the rest of the bot
can run even if the SDK isn't installed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Protocol, Sequence

from bot.auditor.chat.tools import Tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# protocol types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolCall:
    """A backend-agnostic tool-call request emitted by the LLM."""

    name: str
    arguments: dict
    call_id: str = ""  # provider-specific; needed to wire results back to Gemini


@dataclass
class LLMReply:
    """Normalised response from a single LLM round trip."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    raw: Any = None  # provider-native response, useful for debugging


@dataclass
class LLMMessage:
    """Conversation message normalised across providers.

    ``role``: 'system' | 'user' | 'assistant' | 'tool'.
    ``tool_call_id`` is only set for tool-result messages so the backend can
    map the result back to the originating call.
    """

    role: str
    content: str = ""
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None  # tool name for role='tool'


class LLMBackend(Protocol):
    """Provider-agnostic chat interface."""

    available: bool  # False when the SDK isn't installed or no API key

    def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[Tool] | None = None,
        temperature: float = 0.3,
        max_output_tokens: int = 1500,
    ) -> LLMReply:
        ...


# ---------------------------------------------------------------------------
# null backend (tests + disabled state)
# ---------------------------------------------------------------------------


class NullBackend:
    """No-op backend used when chat is disabled or for unit tests.

    Returns a deterministic canned reply that explains why chat is off so the
    user gets a useful Discord message instead of silence.
    """

    available = True

    def __init__(self, reason: str = "Auditor chat is disabled.") -> None:
        self.reason = reason

    def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[Tool] | None = None,
        temperature: float = 0.3,
        max_output_tokens: int = 1500,
    ) -> LLMReply:
        return LLMReply(text=self.reason, tool_calls=[], finish_reason="stop")


# ---------------------------------------------------------------------------
# gemini backend
# ---------------------------------------------------------------------------


class GeminiBackend:
    """google-genai backed LLM client.

    The SDK is imported the first time ``complete`` is called so an absent
    ``google-genai`` package only matters when the user actually tries to chat.
    """

    available = True

    def __init__(self, *, api_key: str, model: str) -> None:
        self.api_key = (api_key or "").strip()
        self.model = (model or "gemini-2.0-flash").strip()
        self._client = None
        self._types = None
        if not self.api_key:
            self.available = False

    def _ensure_client(self):
        if self._client is not None:
            return
        try:
            from google import genai  # type: ignore
            from google.genai import types  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "google-genai package is not installed. Run "
                "`pip install -r requirements.txt` to enable Auditor chat."
            ) from exc
        self._client = genai.Client(api_key=self.api_key)
        self._types = types

    def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[Tool] | None = None,
        temperature: float = 0.3,
        max_output_tokens: int = 1500,
    ) -> LLMReply:
        if not self.available:
            return LLMReply(
                text="Gemini chat unavailable: no API key configured. "
                     "Set GEMINI_API_KEY in .env and restart.",
                finish_reason="error",
            )
        self._ensure_client()
        types = self._types  # local alias for readability
        assert types is not None  # for mypy

        system_text, contents = _split_system_from_contents(messages, types)
        config_kwargs: dict[str, Any] = {
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
        }
        if system_text:
            config_kwargs["system_instruction"] = system_text
        if tools:
            config_kwargs["tools"] = [_tool_to_gemini_declaration(t, types)]

        try:
            response = self._client.models.generate_content(  # type: ignore[union-attr]
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(**config_kwargs),
            )
        except Exception as exc:  # noqa: BLE001 — propagate as a graceful reply
            logger.exception("Gemini generate_content failed")
            return LLMReply(text=f"Gemini error: {exc}", finish_reason="error")

        return _gemini_response_to_reply(response)


# ---------------------------------------------------------------------------
# helpers — kept private; rely on the runtime ``types`` module from google-genai
# ---------------------------------------------------------------------------


def _split_system_from_contents(messages: Sequence[LLMMessage], types):
    """Pop the leading system message; convert the rest to Gemini Content objects."""
    system_text = ""
    rest: list[LLMMessage] = []
    for m in messages:
        if m.role == "system" and not rest:
            system_text = (system_text + "\n" + m.content).strip() if system_text else m.content
        else:
            rest.append(m)
    contents = [_message_to_content(m, types) for m in rest]
    return system_text, contents


def _message_to_content(msg: LLMMessage, types):
    """Build a Gemini Content object from a normalised LLMMessage."""
    if msg.role == "user":
        return types.Content(role="user", parts=[types.Part(text=msg.content)])
    if msg.role == "assistant":
        parts = []
        if msg.content:
            parts.append(types.Part(text=msg.content))
        if msg.tool_calls:
            for tc in msg.tool_calls:
                parts.append(types.Part(function_call=types.FunctionCall(name=tc.name, args=tc.arguments)))
        if not parts:
            parts = [types.Part(text="")]
        return types.Content(role="model", parts=parts)
    if msg.role == "tool":
        return types.Content(
            role="user",  # Gemini funnels function responses back as "user" role parts
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        name=msg.name or "",
                        response=_coerce_tool_response(msg.content),
                    )
                )
            ],
        )
    # Fallback (system handled separately; any unknown role gets stringified)
    return types.Content(role="user", parts=[types.Part(text=msg.content)])


def _coerce_tool_response(payload: str | Mapping[str, Any] | Iterable[Any]) -> Mapping[str, Any]:
    """Gemini's FunctionResponse.response expects a dict; coerce strings/lists."""
    if isinstance(payload, Mapping):
        return dict(payload)
    if isinstance(payload, (list, tuple)):
        return {"items": list(payload)}
    return {"result": payload}


def _tool_to_gemini_declaration(tool: Tool, types):
    """Wrap our Tool descriptors in Gemini FunctionDeclaration objects."""
    function = types.FunctionDeclaration(
        name=tool.name,
        description=tool.description,
        parameters=tool.parameters,
    )
    return types.Tool(function_declarations=[function])


def _gemini_response_to_reply(response: Any) -> LLMReply:
    """Convert a Gemini ``GenerateContentResponse`` to our normalised reply."""
    text_chunks: list[str] = []
    tool_calls: list[ToolCall] = []
    finish_reason = "stop"
    try:
        candidates = getattr(response, "candidates", None) or []
        for cand in candidates:
            fr = getattr(cand, "finish_reason", None)
            if fr is not None:
                finish_reason = str(fr).lower()
            content = getattr(cand, "content", None)
            if content is None:
                continue
            for part in getattr(content, "parts", []) or []:
                txt = getattr(part, "text", None)
                if txt:
                    text_chunks.append(txt)
                fc = getattr(part, "function_call", None)
                if fc is not None and getattr(fc, "name", None):
                    args = getattr(fc, "args", {}) or {}
                    if not isinstance(args, dict):
                        try:
                            args = dict(args)
                        except Exception:  # noqa: BLE001
                            args = {}
                    tool_calls.append(
                        ToolCall(
                            name=str(fc.name),
                            arguments=args,
                            call_id=str(getattr(fc, "id", "") or fc.name),
                        )
                    )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to parse Gemini response")
        return LLMReply(text="(failed to parse Gemini response)", finish_reason="error", raw=response)
    return LLMReply(
        text="\n".join(text_chunks).strip(),
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        raw=response,
    )
