"""Tests for bot.notifications.discord_webhook.post_webhook."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from bot.notifications.discord_webhook import (
    DISCORD_MAX_CHARS,
    _TRUNCATION_SUFFIX,
    post_webhook,
)


class _FakeResponse:
    def __init__(self, status: int = 204):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def _mock_urlopen(status: int = 204):
    return patch(
        "bot.notifications.discord_webhook.urllib.request.urlopen",
        return_value=_FakeResponse(status),
    )


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


def test_post_webhook_success():
    with _mock_urlopen(204) as mock_open:
        result = post_webhook("https://discord.example.com/webhook", "hello")
    assert result is True
    mock_open.assert_called_once()


def test_post_webhook_custom_username():
    with _mock_urlopen(204) as mock_open:
        result = post_webhook(
            "https://discord.example.com/webhook",
            "msg",
            username="Kraken Monitor",
        )
    assert result is True
    # Verify username appears in the encoded payload
    request_arg = mock_open.call_args[0][0]
    assert b"Kraken Monitor" in request_arg.data


# ---------------------------------------------------------------------------
# truncation
# ---------------------------------------------------------------------------


def test_post_webhook_truncates_long_content():
    long_content = "x" * (DISCORD_MAX_CHARS + 100)
    with _mock_urlopen(204):
        result = post_webhook("https://discord.example.com/webhook", long_content)
    assert result is True


def test_truncated_content_ends_with_suffix():
    long_content = "a" * (DISCORD_MAX_CHARS + 100)
    captured: list[bytes] = []

    def fake_urlopen(req, timeout=10):
        captured.append(req.data)
        return _FakeResponse(204)

    with patch(
        "bot.notifications.discord_webhook.urllib.request.urlopen",
        side_effect=fake_urlopen,
    ):
        post_webhook("https://discord.example.com/webhook", long_content)

    import json

    payload = json.loads(captured[0])
    assert payload["content"].endswith(_TRUNCATION_SUFFIX)
    assert len(payload["content"]) <= DISCORD_MAX_CHARS


# ---------------------------------------------------------------------------
# error paths
# ---------------------------------------------------------------------------


def test_post_webhook_http_error_returns_false():
    with _mock_urlopen(403):
        result = post_webhook("https://discord.example.com/webhook", "msg")
    assert result is False


def test_post_webhook_network_exception_returns_false():
    with patch(
        "bot.notifications.discord_webhook.urllib.request.urlopen",
        side_effect=OSError("connection refused"),
    ):
        result = post_webhook("https://discord.example.com/webhook", "msg")
    assert result is False


def test_post_webhook_empty_url_returns_false():
    result = post_webhook("", "msg")
    assert result is False


def test_post_webhook_no_url_returns_false():
    result = post_webhook("   ", "msg")
    assert result is False
