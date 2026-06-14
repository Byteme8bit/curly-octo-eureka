"""Tests for scripts/is_tradebot_running.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import scripts.is_tradebot_running as running_mod
from scripts.is_tradebot_running import tradebot_is_running


def test_tradebot_is_running_false_when_no_lock(tmp_path, monkeypatch):
    lock = tmp_path / "tradebot.lock"
    monkeypatch.setattr(running_mod, "LOCK_FILE", lock)
    assert tradebot_is_running() is False


def test_tradebot_is_running_true_when_pid_live(tmp_path, monkeypatch):
    lock = tmp_path / "tradebot.lock"
    lock.write_text("4242", encoding="utf-8")
    monkeypatch.setattr(running_mod, "LOCK_FILE", lock)
    with patch.object(running_mod, "_pid_is_running", return_value=True), patch.object(
        running_mod, "_pid_is_valid_tradebot_holder", return_value=True
    ):
        assert tradebot_is_running() is True


def test_tradebot_is_running_false_when_pid_dead(tmp_path, monkeypatch):
    lock = tmp_path / "tradebot.lock"
    lock.write_text("4242", encoding="utf-8")
    monkeypatch.setattr(running_mod, "LOCK_FILE", lock)
    with patch.object(running_mod, "_pid_is_running", return_value=False):
        assert tradebot_is_running() is False


def test_tradebot_is_running_false_on_invalid_lock(tmp_path, monkeypatch):
    lock = tmp_path / "tradebot.lock"
    lock.write_text("not-a-pid", encoding="utf-8")
    monkeypatch.setattr(running_mod, "LOCK_FILE", lock)
    assert tradebot_is_running() is False
