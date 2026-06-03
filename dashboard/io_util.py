"""Safe read-only file access (Windows-friendly)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")


def read_text(path: Path, *, retries: int = 4, delay_sec: float = 0.05) -> str | None:
    if not path.exists():
        return None
    last_exc: OSError | None = None
    for attempt in range(retries):
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            last_exc = exc
            if attempt + 1 < retries:
                time.sleep(delay_sec)
    if last_exc:
        return None
    return None


def read_json(path: Path, *, retries: int = 4) -> dict | list | None:
    raw = read_text(path, retries=retries)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def tail_lines(path: Path, *, max_lines: int = 200) -> list[str]:
    raw = read_text(path)
    if not raw:
        return []
    lines = raw.splitlines()
    return lines[-max_lines:] if len(lines) > max_lines else lines


def newest_files(directory: Path, pattern: str, *, limit: int = 20) -> list[Path]:
    if not directory.is_dir():
        return []
    files = sorted(
        directory.glob(pattern),
        key=lambda p: p.stat().st_mtime if p.exists() else 0,
        reverse=True,
    )
    return files[:limit]
