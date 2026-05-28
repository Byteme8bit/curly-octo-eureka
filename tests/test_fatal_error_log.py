"""Tests for bot.fatal_error_log — must work even when optional deps missing."""

from __future__ import annotations

from pathlib import Path

import pytest

from bot.fatal_error_log import (
    ARCHIVE_DIR,
    ERROR_DIR,
    _hint_for,
    archive_all_logs,
    archive_log,
    log_fatal,
)


def test_log_fatal_writes_file_and_returns_path():
    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        path = log_fatal(exc, context="unit test")
    assert path != Path("nul")
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "RuntimeError: boom" in text
    assert "Context: unit test" in text
    assert "Traceback:" in text
    # cleanup
    path.unlink(missing_ok=True)


def test_log_fatal_creates_error_logs_directory():
    try:
        raise ValueError("x")
    except ValueError as exc:
        log_fatal(exc)
    assert ERROR_DIR.exists()


def test_hint_for_module_not_found_mentions_venv():
    exc = ModuleNotFoundError("No module named 'tzdata'", name="tzdata")
    hint = _hint_for(exc)
    # Either suggests venv activation or pip install
    assert "venv" in hint.lower() or "pip install" in hint


def test_hint_for_zoneinfo_error_mentions_tzdata():
    class FakeZoneInfoNotFoundError(Exception):
        pass
    FakeZoneInfoNotFoundError.__name__ = "ZoneInfoNotFoundError"
    exc = FakeZoneInfoNotFoundError("no tz")
    hint = _hint_for(exc)
    assert "tzdata" in hint.lower()


def test_hint_for_unknown_exception_is_empty():
    exc = TypeError("anything")
    assert _hint_for(exc) == ""


def test_log_fatal_never_raises_on_bad_input():
    # Should swallow any internal failure
    log_fatal(Exception("test"))  # no assertion needed — it must not raise


def test_archive_log_moves_file_and_adds_footer():
    try:
        raise RuntimeError("archive-me")
    except RuntimeError as exc:
        src = log_fatal(exc, context="archive test")
    assert src.exists()

    dest = archive_log(src, reason="unit test cleanup")
    assert dest != src
    assert dest.exists()
    assert not src.exists()
    assert dest.parent == ARCHIVE_DIR
    assert dest.name.startswith("archived-")
    text = dest.read_text(encoding="utf-8")
    assert "RuntimeError: archive-me" in text
    assert "Reason:   unit test cleanup" in text
    dest.unlink(missing_ok=True)


def test_archive_log_returns_input_when_missing():
    missing = ERROR_DIR / "does-not-exist.txt"
    result = archive_log(missing)
    assert result == missing


def test_archive_all_logs_moves_every_loose_log():
    created: list[Path] = []
    for i in range(3):
        try:
            raise RuntimeError(f"batch-{i}")
        except RuntimeError as exc:
            created.append(log_fatal(exc, context=f"batch {i}"))

    moved = archive_all_logs(reason="batch test")
    assert len(moved) >= 3
    for src in created:
        assert not src.exists()
    # cleanup
    for p in moved:
        p.unlink(missing_ok=True)
