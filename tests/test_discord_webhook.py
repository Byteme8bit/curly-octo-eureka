"""Tests for bot/notifications/discord_webhook.py (feature 039)."""
from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock, patch

from bot.notifications.discord_webhook import (
    DISCORD_HARD_LIMIT,
    SAFETY_HEADROOM,
    post_webhook,
)


def _mock_response(status: int = 204):
    resp = MagicMock()
    resp.status = status
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def test_success_returns_zero():
    with patch("urllib.request.urlopen", return_value=_mock_response(204)):
        rc = post_webhook("https://example.com/hook", content="hello")
    assert rc == 0


def test_http_error_returns_two(capsys):
    with patch("urllib.request.urlopen", return_value=_mock_response(403)):
        rc = post_webhook("https://example.com/hook", content="hello")
    assert rc == 2
    captured = capsys.readouterr()
    assert "403" in captured.err


def test_network_error_returns_two(capsys):
    with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
        rc = post_webhook("https://example.com/hook", content="hello")
    assert rc == 2
    captured = capsys.readouterr()
    assert "timeout" in captured.err


def test_long_content_is_truncated():
    max_len = DISCORD_HARD_LIMIT - SAFETY_HEADROOM
    long_content = "x" * (max_len + 500)

    captured_payload: list[bytes] = []

    def fake_urlopen(req, timeout):
        captured_payload.append(req.data)
        return _mock_response(204)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        rc = post_webhook("https://example.com/hook", content=long_content)

    assert rc == 0
    import json
    sent = json.loads(captured_payload[0])
    assert len(sent["content"]) <= DISCORD_HARD_LIMIT
    assert "truncated" in sent["content"]


def test_username_passed_in_payload():
    captured_payload: list[bytes] = []

    def fake_urlopen(req, timeout):
        captured_payload.append(req.data)
        return _mock_response(204)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        post_webhook("https://example.com/hook", content="hi", username="TestBot")

    import json
    sent = json.loads(captured_payload[0])
    assert sent["username"] == "TestBot"
