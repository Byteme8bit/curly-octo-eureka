"""Tests for bot/notifications/discord_webhook.py."""

from __future__ import annotations

import sys
import urllib.error
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from bot.notifications.discord_webhook import (
    DISCORD_HARD_LIMIT,
    post_alert,
    post_webhook,
)


# ---------------------------------------------------------------------------
# post_webhook
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status: int = 204):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def _mock_urlopen(status: int = 204):
    return patch(
        "bot.notifications.discord_webhook.urllib.request.urlopen",
        return_value=FakeResponse(status),
    )


def test_post_webhook_success():
    with _mock_urlopen(204) as m:
        rc = post_webhook("https://example.com/hook", "hello")
    assert rc == 0
    assert m.called


def test_post_webhook_empty_webhook_returns_3():
    rc = post_webhook("", "hello")
    assert rc == 3


def test_post_webhook_none_webhook_returns_3():
    rc = post_webhook(None, "hello")
    assert rc == 3


def test_post_webhook_discord_error_returns_2():
    with _mock_urlopen(400) as _:
        rc = post_webhook("https://example.com/hook", "hello")
    assert rc == 2


def test_post_webhook_network_error_returns_2():
    with patch(
        "bot.notifications.discord_webhook.urllib.request.urlopen",
        side_effect=OSError("network down"),
    ):
        rc = post_webhook("https://example.com/hook", "hello")
    assert rc == 2


# ---------------------------------------------------------------------------
# post_alert
# ---------------------------------------------------------------------------


def test_post_alert_formats_title_body():
    captured: list[str] = []

    def fake_urlopen(req, timeout):
        import json
        body = json.loads(req.data.decode("utf-8"))
        captured.append(body["content"])
        return FakeResponse(204)

    with patch(
        "bot.notifications.discord_webhook.urllib.request.urlopen",
        side_effect=fake_urlopen,
    ):
        rc = post_alert("My Title", "Some body", webhook="https://x.com/h")
    assert rc == 0
    assert captured[0].startswith("**My Title**\nSome body")


def test_post_alert_truncates_long_message():
    long_body = "x" * (DISCORD_HARD_LIMIT + 500)
    captured: list[str] = []

    def fake_urlopen(req, timeout):
        import json
        body = json.loads(req.data.decode("utf-8"))
        captured.append(body["content"])
        return FakeResponse(204)

    with patch(
        "bot.notifications.discord_webhook.urllib.request.urlopen",
        side_effect=fake_urlopen,
    ):
        rc = post_alert("T", long_body, webhook="https://x.com/h")
    assert rc == 0
    assert len(captured[0]) <= DISCORD_HARD_LIMIT
    assert "truncated" in captured[0]


def test_post_alert_missing_webhook_returns_3():
    rc = post_alert("T", "B", webhook=None)
    assert rc == 3
