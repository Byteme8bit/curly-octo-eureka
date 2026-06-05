"""Tests for bot.singleton — PID lock-file guard against duplicate instances."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

import bot.singleton as _singleton_mod
from bot.singleton import _pid_is_running, acquire_lock, release_lock


# ---------------------------------------------------------------------------
# Unit tests for _pid_is_running
# ---------------------------------------------------------------------------

def test_pid_is_running_current_process():
    assert _pid_is_running(os.getpid()) is True


def test_pid_is_running_definitely_dead():
    # Mock os.kill to raise OSError to simulate a non-existent process.
    with patch("bot.singleton.os.kill", side_effect=OSError("no such process")):
        assert _pid_is_running(99999) is False


# ---------------------------------------------------------------------------
# Helpers — patch LOCK_FILE to a known temp location
# ---------------------------------------------------------------------------

def _lock_path(tmp_path_: str) -> Path:
    return Path(tmp_path_) / "test_tradebot.lock"


# ---------------------------------------------------------------------------
# acquire_lock — no existing lock file
# ---------------------------------------------------------------------------

def test_acquire_lock_creates_lock_file(tmp_path, monkeypatch):
    lock = tmp_path / "tradebot.lock"
    monkeypatch.setattr(_singleton_mod, "LOCK_FILE", lock)
    acquire_lock()
    assert lock.exists()
    assert lock.read_text(encoding="utf-8").strip() == str(os.getpid())
    lock.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# acquire_lock — stale lock (dead PID) → should succeed and overwrite
# ---------------------------------------------------------------------------

def test_acquire_lock_stale_pid_succeeds(tmp_path, monkeypatch):
    lock = tmp_path / "tradebot.lock"
    lock.write_text("999999999", encoding="utf-8")
    monkeypatch.setattr(_singleton_mod, "LOCK_FILE", lock)
    with patch.object(_singleton_mod, "_pid_is_running", return_value=False):
        acquire_lock()  # must not raise / exit
    assert lock.read_text(encoding="utf-8").strip() == str(os.getpid())
    lock.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# acquire_lock — live duplicate → must exit with code 1
# ---------------------------------------------------------------------------

def test_acquire_lock_live_duplicate_exits(tmp_path, monkeypatch):
    lock = tmp_path / "tradebot.lock"
    fake_pid = os.getpid() + 9999
    lock.write_text(str(fake_pid), encoding="utf-8")
    monkeypatch.setattr(_singleton_mod, "LOCK_FILE", lock)
    with patch.object(_singleton_mod, "_pid_is_running", return_value=True):
        with pytest.raises(SystemExit) as exc_info:
            acquire_lock()
    assert exc_info.value.code == 1
    lock.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# acquire_lock — --take-lock flag bypasses the liveness check
# ---------------------------------------------------------------------------

def test_acquire_lock_take_lock_overwrites_live_pid(tmp_path, monkeypatch):
    lock = tmp_path / "tradebot.lock"
    fake_pid = os.getpid() + 9999
    lock.write_text(str(fake_pid), encoding="utf-8")
    monkeypatch.setattr(_singleton_mod, "LOCK_FILE", lock)
    with patch.object(_singleton_mod, "_pid_is_running", return_value=True):
        # take_lock=True must NOT exit even when another PID is "running"
        acquire_lock(take_lock=True)
    assert lock.read_text(encoding="utf-8").strip() == str(os.getpid())
    lock.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# acquire_lock — our own PID in the lock file (e.g. restart within same PID)
# ---------------------------------------------------------------------------

def test_acquire_lock_own_pid_succeeds(tmp_path, monkeypatch):
    lock = tmp_path / "tradebot.lock"
    lock.write_text(str(os.getpid()), encoding="utf-8")
    monkeypatch.setattr(_singleton_mod, "LOCK_FILE", lock)
    acquire_lock()  # must succeed — same PID is not a duplicate
    lock.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# release_lock — removes the file
# ---------------------------------------------------------------------------

def test_release_lock_removes_file(tmp_path, monkeypatch):
    lock = tmp_path / "tradebot.lock"
    lock.write_text("12345", encoding="utf-8")
    monkeypatch.setattr(_singleton_mod, "LOCK_FILE", lock)
    release_lock()
    assert not lock.exists()


def test_release_lock_missing_file_is_safe(tmp_path, monkeypatch):
    lock = tmp_path / "tradebot.lock"
    monkeypatch.setattr(_singleton_mod, "LOCK_FILE", lock)
    assert not lock.exists()
    release_lock()  # must not raise


# ---------------------------------------------------------------------------
# Corrupt lock file — should not crash, just treat as stale
# ---------------------------------------------------------------------------

def test_acquire_lock_corrupt_content_is_treated_as_stale(tmp_path, monkeypatch):
    lock = tmp_path / "tradebot.lock"
    lock.write_text("not-a-pid", encoding="utf-8")
    monkeypatch.setattr(_singleton_mod, "LOCK_FILE", lock)
    acquire_lock()  # must succeed
    assert lock.read_text(encoding="utf-8").strip() == str(os.getpid())
    lock.unlink(missing_ok=True)
