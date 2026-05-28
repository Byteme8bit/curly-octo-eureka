"""Conversational Auditor — read-only Q&A with an LLM backend.

Public surface:
    - ChatService          : orchestrates a single turn or a multi-turn session.
    - ChatTurn             : a (role, content) pair persisted in conversation memory.
    - ChatResult           : the structured reply returned to the caller.
    - build_tool_registry  : factory that wires read-only callables into Tool descriptors.
    - GeminiBackend        : Gemini implementation of the LLMBackend ABC.
    - NullBackend          : test/dev stub backend.

Everything is opt-in via ``AuditorConfig.chat_enabled`` and gated by a
``GEMINI_API_KEY``. The bot never imports the Gemini SDK unless chat is
enabled at runtime.
"""

from bot.auditor.chat.backends import GeminiBackend, LLMBackend, NullBackend
from bot.auditor.chat.service import ChatResult, ChatService, ChatTurn
from bot.auditor.chat.tools import Tool, ToolRegistry, build_tool_registry

__all__ = [
    "ChatResult",
    "ChatService",
    "ChatTurn",
    "GeminiBackend",
    "LLMBackend",
    "NullBackend",
    "Tool",
    "ToolRegistry",
    "build_tool_registry",
]
