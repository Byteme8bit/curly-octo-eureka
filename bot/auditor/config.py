"""Auditor configuration dataclass loaded from environment variables.

Lives next to the trading engine config but isolated so the rest of the bot
can import the rest of the auditor package without paying for env parsing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AuditorConfig:
    """Settings consumed by `AuditorService`.

    Field names mirror the env-var prefix `AUDITOR_*` to keep grep-ability.
    """

    enabled: bool
    daily_run_hour_pacific: int
    trade_count_trigger: int
    pnl_pct_trigger: float
    news_enabled: bool
    news_provider: str  # comma-separated providers ("rss", "coingecko", "cryptopanic")
    cryptopanic_api_key: str  # optional, only used when "cryptopanic" is in provider list
    rss_feeds: str  # comma-separated "Name|URL" pairs; blank → built-in defaults
    news_max_items: int
    proposals_ttl_minutes: int
    reports_dir: Path
    state_file: Path
    # Sleep-window auto-apply (default OFF — explicit opt-in only)
    autoapply_enabled: bool = False
    autoapply_window_start_hour: int = 1   # inclusive (Pacific)
    autoapply_window_end_hour: int = 7     # exclusive (Pacific)
    autoapply_min_severity: str = "high"   # "low" | "medium" | "high"
    autoapply_max_per_night: int = 1
    autoapply_restart_enabled: bool = True

    # Conversational chat (default OFF — needs GEMINI_API_KEY to enable)
    chat_enabled: bool = False
    chat_backend: str = "gemini"           # "gemini" today; "null" for tests
    # Default to flash-lite — best free-tier headroom of the flash family
    # (15 RPM / 1000 RPD / 250K TPM vs 2.0-flash's 200 RPD).
    chat_model: str = "gemini-2.5-flash-lite"
    chat_api_key: str = ""                 # GEMINI_API_KEY from .env
    chat_max_turns: int = 6                # rolling history per channel (was 10)
    chat_max_tokens: int = 1000            # cap on a single reply (was 1500)
    chat_temperature: float = 0.3          # factual responses
    # Hard cap on LLM<->tool round-trips per question. Lowered from 4→2:
    # most useful answers need at most 1-2 tool waves. Higher means more
    # API requests per chat which eats the free-tier RPD bucket fast.
    chat_tool_iterations: int = 2
    # Per-tool-result truncation (chars). Lower = less context bloat.
    # Each iteration resends the entire conversation, so this dominates
    # token usage when the LLM calls multiple tools.
    chat_tool_result_max_chars: int = 2000  # was 8000 (4x reduction)
