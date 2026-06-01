"""Tests for `bot.discord_bot` command parsing + `clear_recent_messages`.

These tests mock `_request` / `_post_json` so no real Discord HTTP fires.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from bot.discord_bot import (
    DEFAULT_SOURCE,
    DiscordBot,
    DiscordConfig,
    ParsedCommand,
    parse_command,
    source_for_action,
)


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected_action",
    [
        # TradeBot prefix variants
        ("TradeBot -start", "start"),
        ("tradebot -start", "start"),
        ("TRADEBOT -START", "start"),
        ("TB -start", "start"),
        ("tb -start", "start"),
        ("TradeBot start", "start"),       # dash optional
        ("tb start", "start"),
        ("TradeBot -stop", "stop"),
        ("TradeBot -resume", "resume-trading"),
        ("TradeBot -resume-trading", "resume-trading"),
        ("TradeBot -reset", "reset"),
        ("TradeBot -portfolio", "portfolio"),
        ("TradeBot -balance", "portfolio"),
        ("TradeBot -planned", "planned"),
        ("TradeBot -considering", "planned"),
        ("TradeBot -strategy", "strategy"),
        ("TradeBot -strategies", "strategy"),
        ("TradeBot -focus", "strategy"),
        ("TradeBot -help", "tradebot-help"),
        # WatchDog prefix variants
        ("WatchDog -status", "watchdog"),
        ("watchdog -status", "watchdog"),
        ("WD -status", "watchdog"),
        ("wd -status", "watchdog"),
        ("WatchDog status", "watchdog"),
        ("WatchDog -pause", "watchdog-pause"),
        ("wd pause", "watchdog-pause"),
        ("WatchDog -clearchat", "clearchat"),
        ("WD -clearchat", "clearchat"),
        ("WatchDog -clear-chat", "clearchat"),
        ("wd clearchat", "clearchat"),
        ("WatchDog -help", "watchdog-help"),
        # Global utility — no prefix
        ("help", "help"),
        ("HELP", "help"),
        ("commands", "help"),
        ("whoami", "whoami"),
        ("myid", "whoami"),
        ("id", "whoami"),
    ],
)
def test_new_form_parses_to_internal_action(raw: str, expected_action: str) -> None:
    result = parse_command(raw)
    assert result is not None, f"{raw!r} should parse"
    assert result.action == expected_action
    assert result.deprecated is False, f"{raw!r} should NOT be flagged deprecated"


@pytest.mark.parametrize(
    "raw,expected_action",
    [
        ("start", "start"),
        ("go", "start"),
        ("resume", "start"),
        ("stop", "stop"),
        ("pause", "stop"),
        ("halt", "stop"),
        ("resume-trading", "resume-trading"),
        ("clear-circuit", "resume-trading"),
        ("reset", "reset"),
        ("reset paper", "reset"),
        ("reset paper status", "reset"),
        ("portfolio", "portfolio"),
        ("status", "portfolio"),
        ("balance", "portfolio"),
        ("planned", "planned"),
        ("considering", "planned"),
        ("actions", "planned"),
        ("strategy", "strategy"),
        ("strategies", "strategy"),
        ("focus", "strategy"),
        ("watchdog", "watchdog"),
        ("guardian", "watchdog"),
        ("guardian status", "watchdog"),
        ("guardian pause", "watchdog-pause"),
    ],
)
def test_legacy_aliases_resolve_to_same_action_and_are_deprecated(
    raw: str, expected_action: str
) -> None:
    result = parse_command(raw)
    assert result is not None
    assert result.action == expected_action
    assert result.deprecated is True


def test_bang_prefix_is_stripped() -> None:
    result = parse_command("!TradeBot -start")
    assert result is not None
    assert result.action == "start"
    assert result.deprecated is False


def test_bang_prefix_with_legacy_alias() -> None:
    result = parse_command("!start")
    assert result is not None
    assert result.action == "start"
    assert result.deprecated is True


def test_bot_mention_is_stripped() -> None:
    result = parse_command("<@123456789> TradeBot -start")
    assert result is not None
    assert result.action == "start"


def test_bot_mention_with_legacy_alias() -> None:
    result = parse_command("<@!987654321> reset")
    assert result is not None
    assert result.action == "reset"
    assert result.deprecated is True


def test_unknown_text_returns_none() -> None:
    assert parse_command("hello there") is None
    assert parse_command("TradeBot -frobnicate") is None
    assert parse_command("WatchDog -fly") is None


def test_empty_returns_none() -> None:
    assert parse_command("") is None
    assert parse_command("   ") is None
    assert parse_command("<@123>") is None


def test_global_command_not_marked_deprecated() -> None:
    """`help` is a global utility — it should not be flagged deprecated."""
    result = parse_command("help")
    assert result is not None
    assert result.action == "help"
    assert result.deprecated is False


# ---------------------------------------------------------------------------
# Source attribution (Issue 1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action,expected_source",
    [
        ("auditor-review", "Auditor"),
        ("auditor-ask How are we doing?", "Auditor"),
        ("auditor-confirm abc123", "Auditor"),
        ("watchdog", "WatchDog"),
        ("watchdog-pause", "WatchDog"),
        ("clearchat", "WatchDog"),
        ("start", "TradeBot"),
        ("portfolio", "TradeBot"),
        ("help", "TradeBot"),
        ("", "TradeBot"),
        (None, "TradeBot"),
    ],
)
def test_source_for_action_maps_to_owning_subsystem(action, expected_source) -> None:
    assert source_for_action(action) == expected_source


def _webhook_bot(tmp_path: Path) -> DiscordBot:
    """Bot configured with ONLY a webhook (no bot token)."""
    cfg = DiscordConfig(
        enabled=True,
        webhook_url="https://discord.test/webhook",
        bot_token="",
        channel_id="",
        allowed_user_ids=frozenset({"42"}),
        pin_state_file=tmp_path / "pins.json",
        chat_log_enabled=False,
        chat_log_file=tmp_path / "chat.log",
    )
    return DiscordBot(cfg, command_handler=lambda action, uid: "")


class TestWebhookUsernameAttribution:
    def test_default_source_uses_base_username(self, tmp_path: Path) -> None:
        bot = _webhook_bot(tmp_path)
        payloads: list[dict] = []
        with patch.object(bot, "_post_json", side_effect=lambda url, p: payloads.append(p) or {"id": "1"}):
            bot.post_important("hello")
        assert payloads[0]["username"] == "TradeBot"
        assert payloads[0]["content"] == "hello"

    def test_watchdog_source_gets_suffixed_username(self, tmp_path: Path) -> None:
        bot = _webhook_bot(tmp_path)
        payloads: list[dict] = []
        with patch.object(bot, "_post_json", side_effect=lambda url, p: payloads.append(p) or {"id": "1"}):
            bot.post_important("watchdog alert", source="WatchDog")
        assert payloads[0]["username"] == "TradeBot \u00b7 WatchDog"
        # Webhook content is NOT text-prefixed — the username carries attribution.
        assert payloads[0]["content"] == "watchdog alert"

    def test_auditor_source_gets_suffixed_username(self, tmp_path: Path) -> None:
        bot = _webhook_bot(tmp_path)
        payloads: list[dict] = []
        with patch.object(bot, "_post_json", side_effect=lambda url, p: payloads.append(p) or {"id": "1"}):
            bot.send_reply("audit done", source="Auditor")
        assert payloads[0]["username"] == "TradeBot \u00b7 Auditor"


class TestBotTokenAttribution:
    """With a bot token, usernames can't change per message — verify prefixing."""

    def test_non_default_source_prefixes_text(self, tmp_path: Path) -> None:
        bot = _make_bot(tmp_path)  # bot-token only, no webhook
        sent: list[dict] = []

        def fake_request(method: str, url: str, payload: dict | None = None):
            if method == "POST" and url.endswith("/messages"):
                sent.append(payload or {})
            return {"id": "555"}

        with patch.object(bot, "_request", side_effect=fake_request):
            bot.post_important("watchdog paused the bot", source="WatchDog")
        assert sent[0]["content"].startswith("**[WatchDog]** ")
        assert "watchdog paused the bot" in sent[0]["content"]

    def test_default_source_not_prefixed(self, tmp_path: Path) -> None:
        bot = _make_bot(tmp_path)
        sent: list[dict] = []

        def fake_request(method: str, url: str, payload: dict | None = None):
            if method == "POST" and url.endswith("/messages"):
                sent.append(payload or {})
            return {"id": "556"}

        with patch.object(bot, "_request", side_effect=fake_request):
            bot.post_important("trade executed", source=DEFAULT_SOURCE)
        assert sent[0]["content"] == "trade executed"
        assert "[" not in sent[0]["content"]

    def test_command_reply_prefixed_by_source(self, tmp_path: Path) -> None:
        bot = _make_bot(tmp_path)
        sent: list[dict] = []

        def fake_request(method: str, url: str, payload: dict | None = None):
            if method == "POST" and url.endswith("/messages"):
                sent.append(payload or {})
            return {"id": "557"}

        with patch.object(bot, "_request", side_effect=fake_request):
            bot.send_reply("here is the audit", source="Auditor")
        assert sent[0]["content"].startswith("**[Auditor]** ")


# ---------------------------------------------------------------------------
# clear_recent_messages tests
# ---------------------------------------------------------------------------


def _make_bot(tmp_path: Path) -> DiscordBot:
    cfg = DiscordConfig(
        enabled=True,
        webhook_url="",
        bot_token="test-token",
        channel_id="999",
        allowed_user_ids=frozenset({"42"}),
        pin_state_file=tmp_path / "pins.json",
        chat_log_enabled=False,
        chat_log_file=tmp_path / "chat.log",
    )
    return DiscordBot(cfg, command_handler=lambda action, uid: "")


def _recent_ts() -> str:
    # Recent enough that bulk-delete is allowed (well within 14 days).
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _old_ts() -> str:
    # Older than 14 days → must fall back to single DELETE.
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()


class TestClearRecentMessages:
    def test_pinned_messages_skipped(self, tmp_path: Path) -> None:
        bot = _make_bot(tmp_path)
        recent = _recent_ts()
        messages = [
            {"id": "10", "timestamp": recent, "pinned": False},
            {"id": "20", "timestamp": recent, "pinned": True},  # pinned → preserved
            {"id": "30", "timestamp": recent, "pinned": False},
        ]
        calls: list[tuple[str, str, dict | None]] = []

        def fake_request(method: str, url: str, payload: dict | None = None):
            calls.append((method, url, payload))
            if method == "GET" and "/messages" in url and "bulk-delete" not in url:
                # Return the page once, empty on subsequent (pagination terminates).
                return messages if "before=" not in url else []
            return None

        with patch.object(bot, "_request", side_effect=fake_request):
            deleted, skipped = bot.clear_recent_messages()

        assert skipped == 1
        assert deleted == 2

        bulk_calls = [c for c in calls if "bulk-delete" in c[1]]
        assert len(bulk_calls) == 1
        method, url, payload = bulk_calls[0]
        assert method == "POST"
        assert url.endswith("/messages/bulk-delete")
        assert payload == {"messages": ["10", "30"]}

    def test_bulk_delete_payload_uses_post_with_messages_list(
        self, tmp_path: Path
    ) -> None:
        bot = _make_bot(tmp_path)
        recent = _recent_ts()
        messages = [
            {"id": str(i), "timestamp": recent, "pinned": False} for i in range(5)
        ]
        calls: list[tuple[str, str, dict | None]] = []

        def fake_request(method: str, url: str, payload: dict | None = None):
            calls.append((method, url, payload))
            if method == "GET" and "bulk-delete" not in url:
                return messages if "before=" not in url else []
            return None

        with patch.object(bot, "_request", side_effect=fake_request):
            deleted, skipped = bot.clear_recent_messages()

        assert deleted == 5
        assert skipped == 0
        bulk_calls = [c for c in calls if "bulk-delete" in c[1]]
        assert len(bulk_calls) == 1
        method, _, payload = bulk_calls[0]
        assert method == "POST"
        assert payload == {"messages": ["0", "1", "2", "3", "4"]}
        # Bulk delete must NOT use DELETE (Discord's bulk endpoint is POST).
        delete_calls = [c for c in calls if c[0] == "DELETE"]
        assert delete_calls == []

    def test_old_messages_fall_back_to_single_delete(self, tmp_path: Path) -> None:
        bot = _make_bot(tmp_path)
        messages = [
            {"id": "100", "timestamp": _recent_ts(), "pinned": False},
            {"id": "101", "timestamp": _recent_ts(), "pinned": False},
            {"id": "200", "timestamp": _old_ts(), "pinned": False},
        ]
        calls: list[tuple[str, str, dict | None]] = []

        def fake_request(method: str, url: str, payload: dict | None = None):
            calls.append((method, url, payload))
            if method == "GET" and "bulk-delete" not in url:
                return messages if "before=" not in url else []
            return None

        with patch.object(bot, "_request", side_effect=fake_request):
            deleted, skipped = bot.clear_recent_messages()

        assert skipped == 0
        assert deleted == 3
        bulk_calls = [c for c in calls if "bulk-delete" in c[1]]
        single_deletes = [c for c in calls if c[0] == "DELETE"]
        # Two recent ids → one bulk-delete POST with both ids.
        assert len(bulk_calls) == 1
        assert bulk_calls[0][2] == {"messages": ["100", "101"]}
        # The 30-day-old message must be deleted via single DELETE.
        assert len(single_deletes) == 1
        assert "/messages/200" in single_deletes[0][1]

    def test_single_recent_falls_back_to_single_delete(self, tmp_path: Path) -> None:
        """Discord bulk-delete requires 2+ ids — verify our 1-id fallback."""
        bot = _make_bot(tmp_path)
        messages = [{"id": "777", "timestamp": _recent_ts(), "pinned": False}]
        calls: list[tuple[str, str, dict | None]] = []

        def fake_request(method: str, url: str, payload: dict | None = None):
            calls.append((method, url, payload))
            if method == "GET" and "bulk-delete" not in url:
                return messages if "before=" not in url else []
            return None

        with patch.object(bot, "_request", side_effect=fake_request):
            deleted, skipped = bot.clear_recent_messages()

        assert deleted == 1
        assert skipped == 0
        bulk_calls = [c for c in calls if "bulk-delete" in c[1]]
        assert bulk_calls == []
        delete_calls = [c for c in calls if c[0] == "DELETE"]
        assert len(delete_calls) == 1
        assert "/messages/777" in delete_calls[0][1]

    def test_returns_zero_when_no_bot_token(self, tmp_path: Path) -> None:
        cfg = DiscordConfig(
            enabled=True,
            webhook_url="",
            bot_token="",  # no token → can't call API
            channel_id="",
            allowed_user_ids=frozenset(),
            pin_state_file=tmp_path / "pins.json",
            chat_log_enabled=False,
            chat_log_file=tmp_path / "chat.log",
        )
        bot = DiscordBot(cfg, command_handler=lambda a, u: "")
        deleted, skipped = bot.clear_recent_messages()
        assert deleted == 0
        assert skipped == 0

    def test_bulk_delete_failure_falls_back_to_single(self, tmp_path: Path) -> None:
        """If bulk-delete raises (e.g. one bad id), every id is retried singly."""
        bot = _make_bot(tmp_path)
        messages = [
            {"id": "1", "timestamp": _recent_ts(), "pinned": False},
            {"id": "2", "timestamp": _recent_ts(), "pinned": False},
            {"id": "3", "timestamp": _recent_ts(), "pinned": False},
        ]
        calls: list[tuple[str, str, dict | None]] = []

        def fake_request(method: str, url: str, payload: dict | None = None):
            calls.append((method, url, payload))
            if method == "GET" and "bulk-delete" not in url:
                return messages if "before=" not in url else []
            if "bulk-delete" in url:
                raise RuntimeError("HTTP 400 Bad Request: one message is too old")
            return None

        with patch.object(bot, "_request", side_effect=fake_request):
            deleted, skipped = bot.clear_recent_messages()

        # Each id retried as a single DELETE after bulk failure.
        delete_calls = [c for c in calls if c[0] == "DELETE"]
        deleted_ids = [c[1].rsplit("/", 1)[-1] for c in delete_calls]
        assert sorted(deleted_ids) == ["1", "2", "3"]
        assert deleted == 3
        assert skipped == 0


# ---------------------------------------------------------------------------
# Deprecation tracking
# ---------------------------------------------------------------------------


def test_deprecation_logged_once_per_form(tmp_path: Path) -> None:
    bot = _make_bot(tmp_path)
    events: list[str] = []
    # Replace chat_log.log_event with a capturing stub.
    bot.chat_log.log_event = lambda msg: events.append(msg)  # type: ignore[assignment]

    assert bot.note_deprecated_command("start") is True
    assert bot.note_deprecated_command("start") is False  # same form → no second log
    assert bot.note_deprecated_command("reset") is True   # different form → logged
    assert bot.note_deprecated_command("Reset") is False  # case-folded same as 'reset'

    assert len(events) == 2
    joined = " | ".join(events)
    assert "TradeBot -start" in joined
    assert "TradeBot -reset" in joined


def test_parsed_command_dataclass_default_deprecated_false() -> None:
    pc = ParsedCommand(action="start")
    assert pc.deprecated is False
    assert pc.original == ""


# ---------------------------------------------------------------------------
# Reset / session cleanup
# ---------------------------------------------------------------------------


class TestResetSessionCleanup:
    def test_clear_session_errors_empties_counters(self, tmp_path: Path) -> None:
        bot = _make_bot(tmp_path)
        bot._error_last_posted["k1"] = 1.0
        bot._error_pin_occurrences["k1"] = [1.0, 2.0]
        bot.clear_session_errors()
        assert bot._error_last_posted == {}
        assert bot._error_pin_occurrences == {}

    def test_clear_all_pins_unpins_and_deletes_bot_pins(self, tmp_path: Path) -> None:
        bot = _make_bot(tmp_path)
        bot._pin_tracker.register("100")
        bot._pin_tracker.set_startup_pin("200")
        unpinned: list[str] = []
        deleted: list[str] = []

        def fake_unpin(message_id: str, *, update_tracker: bool = True) -> None:
            unpinned.append(message_id)

        def fake_delete(message_id: str) -> None:
            deleted.append(message_id)

        with patch.object(bot, "_bot_id", return_value="bot-1"), patch.object(
            bot,
            "_fetch_channel_pins",
            return_value=[
                {"id": "100", "author": {"id": "bot-1"}},
                {"id": "200", "author": {"id": "bot-1"}},
                {"id": "300", "author": {"id": "other-user"}},
            ],
        ), patch.object(bot, "_unpin_message", side_effect=fake_unpin), patch.object(
            bot, "_delete_message", side_effect=fake_delete
        ):
            cleared = bot.clear_all_pins()

        assert cleared == 2
        assert set(unpinned) == {"100", "200"}
        assert set(deleted) == {"100", "200"}
        assert bot._pin_tracker.ids() == []
        assert bot._pin_tracker.startup_pin_id() is None

    def test_reset_discord_channel_runs_full_cleanup(self, tmp_path: Path) -> None:
        bot = _make_bot(tmp_path)
        with patch.object(bot, "clear_all_pins", return_value=3) as mock_pins, patch.object(
            bot, "clear_session_errors"
        ) as mock_errors, patch.object(
            bot, "clear_recent_messages", return_value=(12, 0)
        ) as mock_clear:
            stats = bot.reset_discord_channel()

        mock_pins.assert_called_once_with()
        mock_errors.assert_called_once_with()
        mock_clear.assert_called_once_with(max_messages=500, exclude_pinned=False)
        assert stats == {"pins_cleared": 3, "deleted": 12, "skipped": 0}
