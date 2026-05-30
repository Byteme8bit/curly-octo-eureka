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

    # When a 429 reports a retry delay <= this many seconds, we'll wait and
    # retry once. Anything longer is surfaced to the user immediately so they
    # aren't left wondering whether Discord hung.
    AUTO_RETRY_MAX_SECONDS = 20.0

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
            config_kwargs["tools"] = [_tool_to_gemini_declaration(t, types) for t in tools]

        def _call():
            return self._client.models.generate_content(  # type: ignore[union-attr]
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(**config_kwargs),
            )

        try:
            response = _call()
        except Exception as exc:  # noqa: BLE001 — categorise into a graceful reply
            kind, retry_after, friendly = _classify_gemini_error(exc, self.model)
            if kind == "rate_limit" and 0 < retry_after <= self.AUTO_RETRY_MAX_SECONDS:
                logger.warning(
                    "Gemini rate-limited; honoring retry_delay=%.1fs and retrying once",
                    retry_after,
                )
                import time as _time
                _time.sleep(retry_after + 0.5)  # small grace cushion
                try:
                    response = _call()
                except Exception as retry_exc:  # noqa: BLE001
                    _, _, friendly_retry = _classify_gemini_error(retry_exc, self.model)
                    logger.warning("Gemini retry also failed: %s", retry_exc)
                    return LLMReply(text=friendly_retry, finish_reason="error")
            else:
                if kind == "rate_limit":
                    logger.warning(
                        "Gemini rate-limited; retry_delay=%.0fs exceeds auto-retry cap",
                        retry_after,
                    )
                else:
                    logger.exception("Gemini generate_content failed")
                return LLMReply(text=friendly, finish_reason="error")

        return _gemini_response_to_reply(response)


_RATE_LIMIT_HINT = (
    "**Gemini free-tier rate limit hit** on model `{model}`. "
    "Wait {retry_after}s and try again, or:\n"
    "• Switch to a different free model in `.env` (e.g. `AUDITOR_CHAT_MODEL=gemini-2.5-flash` "
    "or `gemini-1.5-flash-latest`) and restart.\n"
    "• See your quota at https://ai.dev/gemini-api/docs/rate-limits."
)


def _classify_gemini_error(exc: Exception, model: str) -> tuple[str, float, str]:
    """Translate a raw Gemini SDK exception into ``(kind, retry_after, friendly_text)``.

    ``kind`` is one of: ``"rate_limit"``, ``"auth"``, ``"bad_request"``, ``"server"``,
    ``"network"``, ``"other"``. ``retry_after`` is the suggested seconds to wait
    (0 when not provided / inapplicable). ``friendly_text`` is the message the
    user should see in Discord — never the raw multi-line JSON dump.
    """
    text = str(exc)
    code = _extract_status_code(exc, text)

    if code == 429 or "RESOURCE_EXHAUSTED" in text or "rate limit" in text.lower():
        retry_after = _extract_retry_after_seconds(exc, text)
        friendly = _RATE_LIMIT_HINT.format(
            model=model,
            retry_after=int(retry_after) if retry_after else "a moment",
        )
        return "rate_limit", retry_after, friendly

    if code in (401, 403) or "API_KEY" in text.upper() or "PERMISSION_DENIED" in text:
        return (
            "auth",
            0.0,
            "Gemini auth error: check `GEMINI_API_KEY` in `.env` and that "
            "it has access to the configured model. Restart after fixing.",
        )

    if code == 400 or "INVALID_ARGUMENT" in text:
        return (
            "bad_request",
            0.0,
            f"Gemini rejected the request (bad argument). Detail: {_first_line(text)}",
        )

    if code is not None and 500 <= code < 600:
        return (
            "server",
            5.0,
            f"Gemini upstream error ({code}). Try again in a few seconds.",
        )

    if "DNS" in text.upper() or "Network" in text or "Connection" in text:
        return (
            "network",
            0.0,
            "Could not reach Gemini (network issue). Check your connection and try again.",
        )

    return "other", 0.0, f"Gemini error: {_first_line(text)}"


def _extract_status_code(exc: Exception, text: str) -> int | None:
    """Best-effort HTTP status extraction across SDK exception shapes."""
    for attr in ("code", "status_code", "http_status"):
        val = getattr(exc, attr, None)
        if isinstance(val, int):
            return val
        if isinstance(val, str) and val.isdigit():
            return int(val)
    # Fallback: scrape the leading "429" / "404" out of the message.
    import re as _re

    match = _re.search(r"\b(\d{3})\b", text[:64])
    return int(match.group(1)) if match else None


def _extract_retry_after_seconds(exc: Exception, text: str) -> float:
    """Find the Gemini-suggested retry delay (seconds) — defaults to 0 when absent."""
    for attr in ("retry_delay", "retry_after", "retryDelay"):
        val = getattr(exc, attr, None)
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            return _parse_duration_string(val)
    # Try the verbose JSON-in-string form Gemini uses:
    #   "'retryDelay': '17s'"  /  '"retryDelay":"17s"'
    import re as _re

    match = _re.search(r"retry[_]?[Dd]elay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)\s*s?", text)
    if match:
        return float(match.group(1))
    return 0.0


def _parse_duration_string(value: str) -> float:
    value = value.strip().lower().rstrip("s")
    try:
        return float(value)
    except ValueError:
        return 0.0


def _first_line(text: str, limit: int = 240) -> str:
    """Return only the first informative line of a verbose error blob."""
    first = (text or "").splitlines()[0] if text else ""
    if len(first) > limit:
        first = first[: limit - 1] + "…"
    return first or "(no error detail)"


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
    """Convert a Gemini ``GenerateContentResponse`` to our normalised reply.

    When Gemini returns NO text and NO function calls (safety block, prompt
    block, MAX_TOKENS truncation, or just an empty candidate) we synthesise an
    informative diagnostic text instead of letting an empty reply bubble up as
    a bare ``"(no reply text)"`` line in Discord. The diagnostic includes the
    actual finish_reason / block_reason so the user can act on it (rephrase,
    raise the token cap, etc.) without having to crack open logs.
    """
    text_chunks: list[str] = []
    tool_calls: list[ToolCall] = []
    finish_reason = "stop"
    finish_reasons_seen: list[str] = []
    try:
        candidates = getattr(response, "candidates", None) or []
        for cand in candidates:
            fr = getattr(cand, "finish_reason", None)
            if fr is not None:
                normalised = _normalise_finish_reason(fr)
                finish_reason = normalised
                finish_reasons_seen.append(normalised)
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

    text = "\n".join(text_chunks).strip()

    if not text and not tool_calls:
        diagnostic = _diagnose_empty_response(response, finish_reasons_seen)
        logger.warning(
            "Gemini returned no usable content (finish_reasons=%s, "
            "prompt_feedback=%s, candidate_count=%d)",
            finish_reasons_seen or ["<none>"],
            _safe_repr(getattr(response, "prompt_feedback", None)),
            len(getattr(response, "candidates", None) or []),
        )
        return LLMReply(
            text=diagnostic,
            tool_calls=[],
            finish_reason=finish_reason if finish_reasons_seen else "empty",
            raw=response,
        )

    return LLMReply(
        text=text,
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        raw=response,
    )


def _normalise_finish_reason(value: Any) -> str:
    """Turn the various google-genai finish_reason shapes into a lowercase string."""
    name = getattr(value, "name", None)
    if isinstance(name, str) and name:
        return name.lower()
    text = str(value)
    # Some SDK versions return "FinishReason.SAFETY" — peel the prefix.
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text.lower()


_EMPTY_REPLY_HINTS = {
    "safety": (
        "Gemini blocked the response with the safety filter. "
        "Rephrase the question without keywords that could look adversarial."
    ),
    "recitation": (
        "Gemini blocked the response (recitation filter — content too close "
        "to training data). Ask the same thing in your own words."
    ),
    "max_tokens": (
        "Gemini hit the output-token cap before producing any text. "
        "Ask a narrower question OR raise `AUDITOR_CHAT_MAX_TOKENS` in `.env`."
    ),
    "length": (
        "Gemini hit the output-token cap before producing any text. "
        "Ask a narrower question OR raise `AUDITOR_CHAT_MAX_TOKENS` in `.env`."
    ),
    "blocklist": "Gemini blocked the response (term blocklist).",
    "prohibited_content": "Gemini blocked the response (prohibited content filter).",
    "spii": "Gemini blocked the response (sensitive personal info filter).",
    "malformed_function_call": (
        "Gemini emitted a malformed tool call. This is usually transient — "
        "try the same question again."
    ),
    "other": (
        "Gemini returned an empty response for an unspecified reason. "
        "Try rephrasing or retry in a few seconds."
    ),
}


def _diagnose_empty_response(response: Any, finish_reasons: list[str]) -> str:
    """Build a user-facing message explaining why Gemini returned nothing."""
    pf = getattr(response, "prompt_feedback", None)
    block_reason = getattr(pf, "block_reason", None) if pf is not None else None
    if block_reason:
        return (
            f"Gemini blocked the **prompt** (reason: `{block_reason}`). "
            "The prompt itself tripped a filter — try rephrasing your question."
        )

    for fr in finish_reasons:
        hint = _EMPTY_REPLY_HINTS.get(fr)
        if hint:
            return hint

    if not finish_reasons:
        return (
            "Gemini returned no candidates at all. Likely a transient API "
            "issue — try again. If it keeps happening, check "
            "https://status.cloud.google.com."
        )

    return (
        "Gemini returned an empty response "
        f"(finish_reason=`{finish_reasons[0]}`). "
        "Try rephrasing or running `Auditor -clearchat` and asking again."
    )


def _safe_repr(value: Any, limit: int = 200) -> str:
    """repr() that never raises and never returns multi-kilobyte blobs."""
    if value is None:
        return "<none>"
    try:
        text = repr(value)
    except Exception:  # noqa: BLE001
        text = f"<unreprable {type(value).__name__}>"
    return text if len(text) <= limit else text[: limit - 1] + "…"
