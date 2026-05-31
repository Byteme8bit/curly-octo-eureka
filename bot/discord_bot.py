"""Discord status posts (webhook) and command control (bot token)."""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from bot.discord_chat_log import DiscordChatLog
from bot.error_report import error_dedup_key, format_error_alert
from bot.pin_tracker import PinTracker
from config import ROOT

logger = logging.getLogger(__name__)

DISCORD_API = "https://discord.com/api/v10"
DISCORD_USER_AGENT = "EthTradingBot (paper-trading, 1.0)"

# Discord bulk-delete only accepts messages younger than 14 days.
# Use a 5-minute safety margin so borderline messages aren't rejected.
BULK_DELETE_MAX_AGE = timedelta(days=14) - timedelta(minutes=5)
BULK_DELETE_MIN_BATCH = 2
BULK_DELETE_MAX_BATCH = 100


# Internal action tokens consumed by `TradingEngine.handle_command`.
# Bot prefix + action mapping. Action keys are case-insensitive (lowercased
# before lookup). Values are the internal tokens the engine dispatches on.
TRADEBOT_ACTIONS: dict[str, str] = {
    "start": "start",
    "stop": "stop",
    "resume": "resume-trading",
    "resume-trading": "resume-trading",
    "reset": "reset",
    "portfolio": "portfolio",
    "balance": "portfolio",
    "planned": "planned",
    "considering": "planned",
    "actions": "planned",
    "strategy": "strategy",
    "strategies": "strategy",
    "focus": "strategy",
    "help": "tradebot-help",
}

WATCHDOG_ACTIONS: dict[str, str] = {
    "status": "watchdog",
    "pause": "watchdog-pause",
    "clearchat": "clearchat",
    "clear-chat": "clearchat",
    "clear": "clearchat",
    "help": "watchdog-help",
}

# Auditor commands. Some commands accept trailing args (e.g. proposal id or
# knob name); the parser concatenates them into the dispatched action string
# so the engine handler can split them out with `command.split(maxsplit=1)`.
AUDITOR_ACTIONS: dict[str, str] = {
    "review": "auditor-review",
    "audit": "auditor-review",
    "forecast": "auditor-forecast",
    "predict": "auditor-forecast",
    "strategy": "auditor-strategy",
    "strategies": "auditor-strategy",
    "summary": "auditor-summary",
    "last": "auditor-summary",
    "confirm": "auditor-confirm",
    "apply": "auditor-confirm",
    "pending": "auditor-pending",
    "list": "auditor-pending",
    "revert": "auditor-revert",
    "undo": "auditor-revert",
    "status": "auditor-status",
    "help": "auditor-help",
    "ask": "auditor-ask",
    "chat": "auditor-chat",
    "clearchat": "auditor-clearchat",
    "clear-chat": "auditor-clearchat",
    "chatstatus": "auditor-chatstatus",
    "chat-status": "auditor-chatstatus",
}

# Auditor action tokens that accept a trailing arg string. The parser will
# pack the arg into the dispatched action; the engine handler splits it out.
_AUDITOR_ACTIONS_WITH_ARGS = {
    "auditor-review",
    "auditor-strategy",
    "auditor-confirm",
    "auditor-revert",
    "auditor-ask",
    "auditor-chat",
}

# Global commands (no bot prefix required).
GLOBAL_COMMANDS: dict[str, str] = {
    "help": "help",
    "commands": "help",
    "whoami": "whoami",
    "myid": "whoami",
    "id": "whoami",
}

# Legacy single-word aliases — kept for one release as silent fallbacks.
# Each maps to the same internal action token as before, with a deprecation
# warning logged once per process per form.
LEGACY_ALIASES: dict[str, str] = {
    "start": "start",
    "go": "start",
    "resume": "start",
    "resume-trading": "resume-trading",
    "resume trading": "resume-trading",
    "clear-circuit": "resume-trading",
    "stop": "stop",
    "pause": "stop",
    "halt": "stop",
    "reset": "reset",
    "reset paper": "reset",
    "reset paper status": "reset",
    "portfolio": "portfolio",
    "status": "portfolio",
    "balance": "portfolio",
    "planned": "planned",
    "considering": "planned",
    "actions": "planned",
    "strategy": "strategy",
    "strategies": "strategy",
    "focus": "strategy",
    "watchdog": "watchdog",
    "wd": "watchdog",
    "guardian": "watchdog",
    "watchdog status": "watchdog",
    "wd status": "watchdog",
    "guardian status": "watchdog",
    "watchdog pause": "watchdog-pause",
    "wd pause": "watchdog-pause",
    "guardian pause": "watchdog-pause",
}

# Suggested replacement form shown in the deprecation chat-log line.
DEPRECATED_REPLACEMENTS: dict[str, str] = {
    "start": "TradeBot -start",
    "go": "TradeBot -start",
    "resume": "TradeBot -start",
    "resume-trading": "TradeBot -resume",
    "resume trading": "TradeBot -resume",
    "clear-circuit": "TradeBot -resume",
    "stop": "TradeBot -stop",
    "pause": "TradeBot -stop",
    "halt": "TradeBot -stop",
    "reset": "TradeBot -reset",
    "reset paper": "TradeBot -reset",
    "reset paper status": "TradeBot -reset",
    "portfolio": "TradeBot -portfolio",
    "status": "TradeBot -portfolio",
    "balance": "TradeBot -portfolio",
    "planned": "TradeBot -planned",
    "considering": "TradeBot -planned",
    "actions": "TradeBot -planned",
    "strategy": "TradeBot -strategy",
    "strategies": "TradeBot -strategy",
    "focus": "TradeBot -strategy",
    "watchdog": "WatchDog -status",
    "wd": "WatchDog -status",
    "guardian": "WatchDog -status",
    "watchdog status": "WatchDog -status",
    "wd status": "WatchDog -status",
    "guardian status": "WatchDog -status",
    "watchdog pause": "WatchDog -pause",
    "wd pause": "WatchDog -pause",
    "guardian pause": "WatchDog -pause",
}

_PREFIXED_PATTERN = re.compile(
    r"^(tradebot|tb|watchdog|wd|auditor|audit|au)\s+-?([\w-]+)(?:\s+(.+?))?\s*$",
    re.IGNORECASE,
)
_MENTION_PATTERN = re.compile(r"<@!?\d+>")


@dataclass(frozen=True)
class DiscordConfig:
    enabled: bool
    webhook_url: str
    bot_token: str
    channel_id: str
    allowed_user_ids: frozenset[str]
    poll_interval: float = 2.0
    error_cooldown_sec: float = 900.0
    error_pin_count: int = 3
    error_pin_window_sec: float = 1800.0
    pin_enabled: bool = True
    max_pins_retain: int = 15
    pin_state_file: Path | None = None
    chat_log_enabled: bool = True
    chat_log_file: Path | None = None

    @property
    def can_pin(self) -> bool:
        return bool(self.pin_enabled and self.bot_token and self.channel_id)

    @property
    def can_post_status(self) -> bool:
        return bool(self.webhook_url or (self.bot_token and self.channel_id))

    @property
    def can_listen(self) -> bool:
        return bool(self.enabled and self.bot_token and self.channel_id)


@dataclass(frozen=True)
class ParsedCommand:
    """Result of parsing a Discord message into an internal command token."""

    action: str
    deprecated: bool = False
    original: str = ""


TradeBotHelpText = """**TradeBot commands** (owner only — start/restart/reset):
\u2022 `TradeBot -start` \u2014 resume trading ticks
\u2022 `TradeBot -stop` \u2014 pause trading
\u2022 `TradeBot -resume` \u2014 exit circuit-breaker re-evaluation
\u2022 `TradeBot -reset` \u2014 reset paper balances; clear TradeBot + WatchDog error counts, all pins, and chat
\u2022 `TradeBot -portfolio` \u2014 current holdings and value
\u2022 `TradeBot -planned` \u2014 actions the bot is considering
\u2022 `TradeBot -strategy` \u2014 active strategy plugins
\u2022 `TradeBot -help` \u2014 TradeBot help only

Send `help` for all bots + utility commands."""

WatchDogHelpText = """**WatchDog commands** (monitor + maintenance):
\u2022 `WatchDog -status` \u2014 health score and risk assessment
\u2022 `WatchDog -pause` \u2014 watchdog pauses trade bot
\u2022 `WatchDog -clearchat` \u2014 bulk-delete recent channel messages (skips pinned)
\u2022 `WatchDog -help` \u2014 WatchDog help only

Send `help` for all bots + utility commands."""

AuditorHelpText = """**Auditor commands** (read-only review + tier-2 proposals + chat):
\u2022 `Auditor -review` \u2014 audit recent trades + fetch news + propose changes
\u2022 `Auditor -forecast` \u2014 audit with PnL forecast bands highlighted
\u2022 `Auditor -strategy <name>` \u2014 review focused on the listed strategy
\u2022 `Auditor -summary` \u2014 quick recap of the most recent audit
\u2022 `Auditor -pending` \u2014 list pending proposals + active runtime overrides
\u2022 `Auditor -confirm <id>` \u2014 apply a proposal (writes runtime_overrides.json)
\u2022 `Auditor -revert <knob>` \u2014 remove an active runtime override
\u2022 `Auditor -status` \u2014 service status (next scheduled run, triggers, chat config)
\u2022 `Auditor -ask <question>` \u2014 single-turn Q&A about TradeBot/WatchDog state
\u2022 `Auditor -chat <message>` \u2014 multi-turn conversation (keeps history per channel)
\u2022 `Auditor -clearchat` \u2014 wipe the chat history for this channel
\u2022 `Auditor -chatstatus` \u2014 backend, model, history sizes
\u2022 `Auditor -help` \u2014 this message

Shortcuts: `Audit -<action>` and `Au -<action>` are also accepted.
Auditor never edits `.env`; reversions are just key removals. Chat is strictly read-only."""

HelpText = """**TradeBot commands** (owner only \u2014 start/restart/reset):
\u2022 `TradeBot -start` \u2014 resume trading ticks
\u2022 `TradeBot -stop` \u2014 pause trading
\u2022 `TradeBot -resume` \u2014 exit circuit-breaker re-evaluation
\u2022 `TradeBot -reset` \u2014 reset paper balances; clear TradeBot + WatchDog error counts, all pins, and chat
\u2022 `TradeBot -portfolio` \u2014 current holdings and value
\u2022 `TradeBot -planned` \u2014 actions the bot is considering
\u2022 `TradeBot -strategy` \u2014 active strategy plugins
\u2022 `TradeBot -help` \u2014 TradeBot help only

**WatchDog commands** (monitor + maintenance):
\u2022 `WatchDog -status` \u2014 health score and risk assessment
\u2022 `WatchDog -pause` \u2014 watchdog pauses trade bot
\u2022 `WatchDog -clearchat` \u2014 bulk-delete recent channel messages (skips pinned)
\u2022 `WatchDog -help` \u2014 WatchDog help only

**Auditor commands** (read-only review + tier-2 proposals):
\u2022 `Auditor -review` \u2014 audit trades + news + proposals
\u2022 `Auditor -forecast` \u2014 forecast bands highlighted
\u2022 `Auditor -pending` \u2014 list pending proposals + active overrides
\u2022 `Auditor -confirm <id>` \u2014 apply a tier-2 proposal
\u2022 `Auditor -revert <knob>` \u2014 remove an active override
\u2022 `Auditor -help` \u2014 Auditor help only

**Utility:**
\u2022 `help` \u2014 this message
\u2022 `whoami` \u2014 show your Discord user ID"""


def parse_command(content: str) -> ParsedCommand | None:
    """Parse a Discord message into a `ParsedCommand`.

    Accepted forms (all case-insensitive, optional leading `!`, mentions stripped):
        - ``TradeBot -<action>`` / ``TradeBot <action>`` / ``TB -<action>``
        - ``WatchDog -<action>`` / ``wd <action>``
        - Global utility commands (``help``, ``whoami``, ...)
        - Legacy single-word commands (``start``, ``reset``, ...) flagged
          ``deprecated=True`` so callers can surface a one-time warning.
    """

    if not content:
        return None
    text = _MENTION_PATTERN.sub("", content).strip()
    if text.startswith("!"):
        text = text[1:].strip()
    if not text:
        return None

    lower = text.lower()

    # Global utility commands take priority and are never marked deprecated.
    global_action = GLOBAL_COMMANDS.get(lower)
    if global_action:
        return ParsedCommand(action=global_action, deprecated=False, original=text)

    prefixed = _match_prefixed(text)
    if prefixed:
        return prefixed

    legacy_action = LEGACY_ALIASES.get(lower)
    if legacy_action:
        return ParsedCommand(action=legacy_action, deprecated=True, original=lower)

    return None


def _match_prefixed(text: str) -> ParsedCommand | None:
    match = _PREFIXED_PATTERN.match(text)
    if not match:
        return None
    bot_raw = match.group(1).lower()
    action_raw = match.group(2).lower()
    args_raw = (match.group(3) or "").strip()
    if bot_raw in {"tradebot", "tb"}:
        if args_raw:
            return None  # TradeBot commands take no trailing args
        action = TRADEBOT_ACTIONS.get(action_raw)
    elif bot_raw in {"watchdog", "wd"}:
        if args_raw:
            return None  # WatchDog commands take no trailing args
        action = WATCHDOG_ACTIONS.get(action_raw)
    else:  # auditor / audit / au
        action = AUDITOR_ACTIONS.get(action_raw)
        if action and args_raw:
            if action in _AUDITOR_ACTIONS_WITH_ARGS:
                action = f"{action} {args_raw}"
            else:
                return None
    if not action:
        return None
    return ParsedCommand(action=action, deprecated=False, original=text)


class DiscordBot:
    def __init__(
        self,
        config: DiscordConfig,
        *,
        command_handler: Callable[[str, str], str],
    ):
        self.config = config
        self.command_handler = command_handler
        self._last_message_id: str | None = None
        self._last_status_key: str | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._error_last_posted: dict[str, float] = {}
        self._error_pin_occurrences: dict[str, list[float]] = {}
        self._error_cooldown_sec = config.error_cooldown_sec
        self._error_pin_count = config.error_pin_count
        self._error_pin_window_sec = config.error_pin_window_sec
        self.on_error: Callable[[str, BaseException], None] | None = None
        self._pin_lock = threading.Lock()
        pin_file = config.pin_state_file or (ROOT / ".discord_pins.json")
        self._pin_tracker = PinTracker(
            pin_file,
            config.channel_id,
            config.max_pins_retain,
        )
        self._bot_user_id: str | None = None
        chat_path = config.chat_log_file or (ROOT / "logs" / "discord_chat.log")
        self.chat_log = DiscordChatLog(chat_path, enabled=config.chat_log_enabled)
        self._deprecation_logged: set[str] = set()

    def start(self) -> None:
        if self.config.can_pin:
            self._sync_pin_state()
        if not self.config.can_listen:
            return
        self._thread = threading.Thread(target=self._poll_loop, name="discord-listener", daemon=True)
        self._thread.start()
        logger.warning("Discord command listener started")
        self.chat_log.log_event("Discord listener started")

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=self.config.poll_interval * 5)
        self._thread = None
        self.chat_log.log_event("Discord listener stopped")

    def _should_pin_error(self, key: str) -> bool:
        now = time.monotonic()
        times = self._error_pin_occurrences.setdefault(key, [])
        times.append(now)
        cutoff = now - self._error_pin_window_sec
        recent = [ts for ts in times if ts >= cutoff]
        self._error_pin_occurrences[key] = recent
        return len(recent) > self._error_pin_count

    def post_status(self, title: str, body: str, *, summary_key: str, force: bool = False) -> None:
        # Override of base method to mirror to chat log.
        if not self.config.enabled or not self.config.can_post_status:
            return
        if not force and summary_key == self._last_status_key:
            return
        self._last_status_key = summary_key
        content = f"**{title}**\n```\n{_truncate(body, 1800)}\n```"
        self.chat_log.log_outbound(content=f"{title}: {body}", kind="status")
        self._send_message(content)

    def post_startup_pin(self, content: str) -> None:
        """Replace the pinned startup message (unpins/deletes the previous one)."""
        if not self.config.enabled or not self.config.can_post_status:
            return
        with self._pin_lock:
            previous = self._pin_tracker.startup_pin_id()
            if previous:
                self._unpin_message(previous, update_tracker=False)
                self._delete_message(previous)
                self._pin_tracker.clear_startup_pin()

            message_id = self._send_message(_truncate(content, 1990))
            if not message_id:
                return
            if self.config.can_pin:
                try:
                    url = f"{DISCORD_API}/channels/{self.config.channel_id}/pins/{message_id}"
                    self._request("PUT", url)
                    self._pin_tracker.set_startup_pin(message_id)
                except Exception as exc:
                    logger.warning("Discord startup pin failed: %s", _format_discord_error(exc))

    def post_plain(self, content: str, *, pin: bool = False) -> None:
        """Post a simple line to Discord (no dedup). Used for startup/heartbeat."""
        if not self.config.enabled or not self.config.can_post_status:
            return
        self.post_important(content, pin=pin)

    def post_important(self, content: str, *, pin: bool = False) -> None:
        if not self.config.enabled or not self.config.can_post_status:
            return
        message_id = self._send_message(_truncate(content, 1990))
        self.chat_log.log_outbound(content=content, pin=pin, kind="important")
        if pin and message_id:
            self._pin_message(message_id)

    def post_error(self, context: str, exc: BaseException) -> None:
        """Post an error alert with troubleshooting tips (deduped, pinned)."""
        if not self.config.enabled or not self.config.can_post_status:
            return
        key = error_dedup_key(context, exc)
        now = time.monotonic()
        if now - self._error_last_posted.get(key, 0.0) < self._error_cooldown_sec:
            return
        self._error_last_posted[key] = now
        pin = self._should_pin_error(key)
        self.post_important(format_error_alert(context, exc), pin=pin)

    def send_reply(self, content: str) -> None:
        if not self.config.enabled:
            return
        text = _truncate(content, 1990)
        self.chat_log.log_outbound(content=content, kind="reply")
        if self.config.bot_token and self.config.channel_id:
            try:
                url = f"{DISCORD_API}/channels/{self.config.channel_id}/messages"
                self._request("POST", url, {"content": text})
                return
            except Exception as exc:
                logger.warning("Discord bot reply failed: %s", exc)
        if self.config.webhook_url:
            try:
                self._post_json(self.config.webhook_url, {"content": text})
            except Exception as exc:
                logger.warning("Discord webhook reply failed: %s", exc)

    def _send_message(self, content: str) -> str | None:
        # Prefer bot token — webhooks cannot be pinned and may 403 if revoked.
        if self.config.bot_token and self.config.channel_id:
            try:
                url = f"{DISCORD_API}/channels/{self.config.channel_id}/messages"
                result = self._request("POST", url, {"content": content})
                if isinstance(result, dict):
                    return str(result.get("id")) if result.get("id") else None
            except Exception as exc:
                logger.warning("Discord bot post failed: %s", _format_discord_error(exc))
        if self.config.webhook_url:
            try:
                result = self._post_json(self.config.webhook_url, {"content": content})
                if isinstance(result, dict) and result.get("id"):
                    return str(result["id"])
            except Exception as exc:
                logger.warning("Discord webhook post failed: %s", _format_discord_error(exc))
        return None

    def _pin_message(self, message_id: str) -> None:
        if not self.config.can_pin:
            return
        with self._pin_lock:
            self._free_pin_slots()
            try:
                url = f"{DISCORD_API}/channels/{self.config.channel_id}/pins/{message_id}"
                self._request("PUT", url)
                self._pin_tracker.register(message_id)
            except Exception as exc:
                if self._retry_pin_after_channel_cleanup(message_id):
                    return
                logger.warning("Discord pin failed: %s", _format_discord_error(exc))

    def _free_pin_slots(self) -> None:
        while self._pin_tracker.at_capacity():
            oldest = self._pin_tracker.pop_oldest()
            if not oldest:
                break
            self._unpin_message(oldest, update_tracker=False)

    def _unpin_message(self, message_id: str, *, update_tracker: bool = True) -> None:
        try:
            url = f"{DISCORD_API}/channels/{self.config.channel_id}/pins/{message_id}"
            self._request("DELETE", url)
            if update_tracker:
                self._pin_tracker.remove(message_id)
        except Exception as exc:
            logger.warning("Discord unpin failed for %s: %s", message_id, _format_discord_error(exc))
            if update_tracker:
                self._pin_tracker.remove(message_id)

    def _delete_message(self, message_id: str) -> None:
        if not self.config.bot_token or not self.config.channel_id:
            return
        try:
            url = f"{DISCORD_API}/channels/{self.config.channel_id}/messages/{message_id}"
            self._request("DELETE", url)
        except Exception as exc:
            logger.warning("Discord delete failed for %s: %s", message_id, _format_discord_error(exc))

    def _bot_id(self) -> str | None:
        if self._bot_user_id:
            return self._bot_user_id
        if not self.config.bot_token:
            return None
        try:
            me = self._request("GET", f"{DISCORD_API}/users/@me")
            if isinstance(me, dict) and me.get("id"):
                self._bot_user_id = str(me["id"])
                return self._bot_user_id
        except Exception as exc:
            logger.warning("Could not fetch bot user id: %s", exc)
        return None

    def _fetch_channel_pins(self) -> list[dict]:
        url = f"{DISCORD_API}/channels/{self.config.channel_id}/pins"
        result = self._request("GET", url)
        return result if isinstance(result, list) else []

    def _sync_pin_state(self) -> None:
        """Align local pin tracker with live channel pins from this bot."""
        bot_id = self._bot_id()
        if not bot_id:
            return
        pins = self._fetch_channel_pins()
        bot_pin_ids = [
            str(m["id"])
            for m in pins
            if m.get("id") and str(m.get("author", {}).get("id")) == bot_id
        ]
        bot_pin_ids.sort(key=int)
        self._pin_tracker.reconcile(bot_pin_ids)
        startup = self._pin_tracker.startup_pin_id()
        while len(self._pin_tracker.ids()) > self._pin_tracker.max_retain:
            oldest = self._pin_tracker.pop_oldest()
            if not oldest or oldest == startup:
                break
            self._unpin_message(oldest, update_tracker=False)

    def _retry_pin_after_channel_cleanup(self, message_id: str) -> bool:
        """If Discord pin limit hit, unpin oldest bot message and retry once."""
        bot_id = self._bot_id()
        if not bot_id:
            return False
        pins = self._fetch_channel_pins()
        bot_pins = [
            m for m in pins
            if str(m.get("author", {}).get("id")) == bot_id and m.get("id")
        ]
        if not bot_pins:
            return False
        bot_pins.sort(key=lambda m: int(m["id"]))
        startup = self._pin_tracker.startup_pin_id()
        for m in bot_pins:
            mid = str(m["id"])
            if mid == startup:
                continue
            self._unpin_message(mid)
            break
        else:
            return False
        try:
            url = f"{DISCORD_API}/channels/{self.config.channel_id}/pins/{message_id}"
            self._request("PUT", url)
            self._pin_tracker.register(message_id)
            return True
        except Exception:
            return False

    def clear_recent_messages(
        self,
        *,
        max_messages: int = 500,
        exclude_pinned: bool = True,
    ) -> tuple[int, int]:
        """Bulk-delete recent channel messages.

        Returns ``(deleted_count, skipped_count)``. ``skipped_count`` is the
        number of pinned messages preserved when ``exclude_pinned`` is True.

        Messages older than ~14 days are deleted one-at-a-time (Discord's
        bulk-delete endpoint rejects them with HTTP 400). Messages newer than
        that are batched into POST `/messages/bulk-delete` calls of up to 100
        IDs at a time. Pinned messages are preserved by default so the user
        keeps their startup status pin.
        """
        if not self.config.bot_token or not self.config.channel_id:
            return (0, 0)

        base = f"{DISCORD_API}/channels/{self.config.channel_id}/messages"
        fetched: list[dict] = self._fetch_messages(base, max_messages)
        if not fetched:
            return (0, 0)

        skipped = 0
        bulk_ids: list[str] = []
        old_ids: list[str] = []
        cutoff = datetime.now(timezone.utc) - BULK_DELETE_MAX_AGE
        for msg in fetched[:max_messages]:
            mid = msg.get("id")
            if not mid:
                continue
            if exclude_pinned and msg.get("pinned"):
                skipped += 1
                continue
            if _message_is_older_than(msg, cutoff):
                old_ids.append(str(mid))
            else:
                bulk_ids.append(str(mid))

        deleted = 0
        for chunk_start in range(0, len(bulk_ids), BULK_DELETE_MAX_BATCH):
            chunk = bulk_ids[chunk_start:chunk_start + BULK_DELETE_MAX_BATCH]
            deleted += self._delete_chunk(base, chunk)

        for mid in old_ids:
            self._delete_message(mid)
            deleted += 1

        return (deleted, skipped)

    def clear_session_errors(self) -> None:
        """Clear in-memory TradeBot error dedup and pin-burst counters."""
        self._error_last_posted.clear()
        self._error_pin_occurrences.clear()

    def clear_all_pins(self) -> int:
        """Unpin and delete every bot-authored pinned message in the channel."""
        if not self.config.bot_token or not self.config.channel_id:
            with self._pin_lock:
                self._pin_tracker.clear_all()
            return 0

        bot_id = self._bot_id()
        pins = self._fetch_channel_pins()
        cleared = 0
        with self._pin_lock:
            for msg in pins:
                mid = msg.get("id")
                if not mid:
                    continue
                author_id = str(msg.get("author", {}).get("id", ""))
                if bot_id and author_id != bot_id:
                    continue
                mid_str = str(mid)
                self._unpin_message(mid_str, update_tracker=False)
                self._delete_message(mid_str)
                cleared += 1
            self._pin_tracker.clear_all()
        return cleared

    def reset_discord_channel(self, *, max_messages: int = 500) -> dict[str, int]:
        """Full Discord reset for TradeBot -reset: pins, messages, error counters."""
        pins_cleared = self.clear_all_pins()
        self.clear_session_errors()
        deleted, skipped = self.clear_recent_messages(
            max_messages=max_messages,
            exclude_pinned=False,
        )
        return {
            "pins_cleared": pins_cleared,
            "deleted": deleted,
            "skipped": skipped,
        }

    def _fetch_messages(self, base_url: str, limit: int) -> list[dict]:
        """Page through channel messages newest-first up to ``limit`` items."""
        fetched: list[dict] = []
        before: str | None = None
        while len(fetched) < limit:
            url = f"{base_url}?limit=100"
            if before:
                url = f"{url}&before={before}"
            try:
                batch = self._request("GET", url)
            except Exception as exc:
                logger.warning("clearchat fetch failed: %s", _format_discord_error(exc))
                break
            if not isinstance(batch, list) or not batch:
                break
            fetched.extend(batch)
            last_id = batch[-1].get("id")
            if not last_id:
                break
            before = str(last_id)
            if len(batch) < 100:
                break
        return fetched

    def _delete_chunk(self, base_url: str, chunk: list[str]) -> int:
        """Bulk-delete a ≤100-id chunk; fall back to single deletes on error."""
        if not chunk:
            return 0
        if len(chunk) >= BULK_DELETE_MIN_BATCH:
            try:
                self._request("POST", f"{base_url}/bulk-delete", {"messages": chunk})
                return len(chunk)
            except Exception as exc:
                logger.warning("Discord bulk-delete failed: %s", _format_discord_error(exc))
        # Single-message fallback (also used when chunk has only 1 id).
        for mid in chunk:
            self._delete_message(mid)
        return len(chunk)

    def note_deprecated_command(self, original_form: str) -> bool:
        """Record a one-time deprecation event for a legacy command form.

        Returns True if this is the first time we've seen ``original_form`` in
        this process (and a log line was emitted), False otherwise.
        """
        key = original_form.strip().lower()
        if not key or key in self._deprecation_logged:
            return False
        self._deprecation_logged.add(key)
        replacement = DEPRECATED_REPLACEMENTS.get(key, "the new prefixed form")
        self.chat_log.log_event(
            f"Deprecated command used: '{key}' \u2014 use '{replacement}' instead."
        )
        return True

    # Transient upstream hiccups (Discord/Cloudflare) — expected occasionally and
    # self-healing. We log these quietly and only escalate if they persist.
    _TRANSIENT_MARKERS = (
        "HTTP 429", "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504",
        "Service Unavailable", "Bad Gateway", "Gateway Time-out",
        "connection termination", "disconnect/reset", "timed out",
    )

    def _poll_loop(self) -> None:
        consecutive_transient = 0
        while not self._stop_event.is_set():
            try:
                self._poll_commands()
                consecutive_transient = 0
            except Exception as exc:
                msg = str(exc)
                if any(m in msg for m in self._TRANSIENT_MARKERS):
                    consecutive_transient += 1
                    first_line = msg.splitlines()[0] if msg else repr(exc)
                    logger.warning(
                        "Discord poll transient error #%d (self-healing): %s",
                        consecutive_transient, first_line,
                    )
                    # Only bother the user if it stays broken for a while.
                    if consecutive_transient == 15 and self.on_error:
                        self.on_error("Discord command listener (persistent upstream errors)", exc)
                else:
                    logger.exception("Discord command poll failed")
                    if self.on_error:
                        self.on_error("Discord command listener", exc)
            self._stop_event.wait(self.config.poll_interval)

    def _poll_commands(self) -> None:
        url = f"{DISCORD_API}/channels/{self.config.channel_id}/messages?limit=10"
        messages = self._request("GET", url)
        if not isinstance(messages, list):
            return

        # First poll: skip history so restart doesn't re-run old commands.
        if self._last_message_id is None:
            ids = [int(m["id"]) for m in messages if m.get("id")]
            if ids:
                self._last_message_id = str(max(ids))
            return

        for message in reversed(messages):
            msg_id = message.get("id")
            if not msg_id:
                continue
            if int(msg_id) <= int(self._last_message_id):
                continue

            self._last_message_id = msg_id
            if message.get("author", {}).get("bot"):
                continue

            author_id = str(message.get("author", {}).get("id", ""))
            author_name = message.get("author", {}).get("global_name") or message.get("author", {}).get("username", "unknown")

            content = message.get("content", "")
            parsed = parse_command(content)
            action = parsed.action if parsed else None
            self.chat_log.log_inbound(
                user=str(author_name),
                user_id=author_id,
                content=content,
                command=action,
            )

            if parsed and parsed.deprecated:
                self.note_deprecated_command(parsed.original)

            if action == "whoami":
                self.send_reply(
                    f"Your Discord user ID is `{author_id}` ({author_name}).\n"
                    "Add it to `.env` as `DISCORD_ALLOWED_USER_IDS=` then restart the bot."
                )
                continue

            if author_id not in self.config.allowed_user_ids:
                if action and self.config.allowed_user_ids:
                    continue
                if action and not self.config.allowed_user_ids:
                    self.send_reply(
                        "Commands are locked until `DISCORD_ALLOWED_USER_IDS` is set in `.env`.\n"
                        f"Send `whoami` to get your ID (`{author_id}` if you are {author_name})."
                    )
                continue

            if not action:
                continue

            try:
                reply = self.command_handler(action, author_id)
            except Exception as exc:
                logger.exception("Discord command %s failed", action)
                if self.on_error:
                    self.on_error(f"Discord command `{action}`", exc)
                reply = f"Command `{action}` failed \u2014 check bot logs."

            if reply:
                self.send_reply(reply)

    def _request(self, method: str, url: str, payload: dict | None = None):
        headers = {
            "Authorization": f"Bot {self.config.bot_token}",
            "User-Agent": DISCORD_USER_AGENT,
        }
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8")
                if not raw:
                    return None
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(_read_http_error(exc)) from exc

    def _post_json(self, url: str, payload: dict) -> dict | None:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": DISCORD_USER_AGENT,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8")
                if resp.status >= 400:
                    raise urllib.error.HTTPError(url, resp.status, resp.reason, resp.headers, None)
                if raw:
                    return json.loads(raw)
                return None
        except urllib.error.HTTPError as exc:
            raise RuntimeError(_read_http_error(exc)) from exc


def _read_http_error(exc: urllib.error.HTTPError) -> str:
    body = ""
    try:
        body = exc.read().decode("utf-8", errors="replace")
        parsed = json.loads(body)
        if isinstance(parsed, dict):
            msg = parsed.get("message", "")
            code = parsed.get("code", "")
            return f"HTTP {exc.code} {exc.reason}: {msg} (code {code})"
    except Exception:
        pass
    if body:
        return f"HTTP {exc.code} {exc.reason}: {body[:200]}"
    return f"HTTP {exc.code} {exc.reason}"


def _format_discord_error(exc: Exception) -> str:
    if isinstance(exc, RuntimeError):
        return str(exc)
    if isinstance(exc, urllib.error.HTTPError):
        return _read_http_error(exc)
    return str(exc)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _message_is_older_than(message: dict, cutoff: datetime) -> bool:
    """True when the Discord message timestamp is older than ``cutoff``.

    If the timestamp is missing or unparseable we conservatively treat the
    message as too old to bulk-delete so a single-message DELETE is used
    instead — that's the safer of the two failure modes.
    """
    ts_raw = message.get("timestamp")
    if not ts_raw:
        return True
    try:
        normalized = ts_raw.replace("Z", "+00:00") if ts_raw.endswith("Z") else ts_raw
        msg_dt = datetime.fromisoformat(normalized)
    except (TypeError, ValueError):
        return True
    if msg_dt.tzinfo is None:
        msg_dt = msg_dt.replace(tzinfo=timezone.utc)
    return msg_dt < cutoff
