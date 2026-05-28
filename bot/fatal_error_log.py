"""Fatal-error logger — minimal imports so it works even if optional deps are missing.

Used by `main.py` to capture crashes that prevent the bot from launching
(missing modules, bad config, etc.). Writes a timestamped file to `Error Logs/`.
"""

from __future__ import annotations

import os
import platform
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ERROR_DIR = ROOT / "Error Logs"
ARCHIVE_DIR = ERROR_DIR / "archived"


def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def archive_log(path: Path, *, reason: str = "handled") -> Path:
    """Move a fatal-error log into `Error Logs/archived/`.

    Prepends an `archived-YYYY-MM-DD_HHMMSS--` prefix so order/history is clear,
    and appends a short footer noting why/when. Never raises on filesystem errors.
    """
    src = Path(path)
    if not src.exists() or src.is_dir():
        return src
    try:
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        return src

    dest = ARCHIVE_DIR / f"archived-{_stamp()}--{src.name}"
    counter = 1
    while dest.exists():
        dest = ARCHIVE_DIR / f"archived-{_stamp()}--{counter}--{src.name}"
        counter += 1

    try:
        text = src.read_text(encoding="utf-8", errors="replace")
        footer = (
            "\n"
            + "=" * 70
            + f"\n  Archived: {datetime.now().isoformat()}\n"
            + f"  Reason:   {reason}\n"
            + "=" * 70
            + "\n"
        )
        dest.write_text(text + footer, encoding="utf-8")
        src.unlink()
    except OSError:
        return src
    return dest


def archive_all_logs(*, reason: str = "handled") -> list[Path]:
    """Archive every loose `*_fatal.txt` directly under `Error Logs/`."""
    if not ERROR_DIR.exists():
        return []
    archived: list[Path] = []
    for entry in sorted(ERROR_DIR.iterdir()):
        if entry.is_file() and entry.suffix == ".txt":
            result = archive_log(entry, reason=reason)
            if result != entry:
                archived.append(result)
    return archived


def _hint_for(exc: BaseException) -> str:
    """User-actionable hint based on exception type/message."""
    text = str(exc)
    if isinstance(exc, ModuleNotFoundError):
        missing = getattr(exc, "name", None) or text
        venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
        running_python = Path(sys.executable)
        if venv_python.exists() and running_python != venv_python:
            return (
                f"You ran `{running_python}` (system Python) but the project's "
                f"virtual environment is at `{venv_python}`.\n"
                f"Activate it first:\n"
                f"    .\\.venv\\Scripts\\Activate.ps1\n"
                f"...then re-run `python main.py`.\n"
                f"Or invoke it directly: `.\\.venv\\Scripts\\python.exe main.py`"
            )
        return (
            f"Missing dependency `{missing}`. Install with:\n"
            f"    pip install -r requirements.txt"
        )
    if "ZoneInfoNotFoundError" in type(exc).__name__:
        return (
            "Windows Python can't find timezone data — install `tzdata`:\n"
            "    pip install tzdata\n"
            "(Or activate the project venv where it's already installed.)"
        )
    if isinstance(exc, FileNotFoundError):
        return f"Missing file: {text}"
    if isinstance(exc, PermissionError):
        return f"Permission denied: {text}"
    return ""


def log_fatal(exc: BaseException, *, context: str = "") -> Path:
    """Write a timestamped fatal-error log. Never raises."""
    try:
        ERROR_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        return Path(os.devnull)

    path = ERROR_DIR / f"{_stamp()}_fatal.txt"
    counter = 1
    while path.exists():
        path = ERROR_DIR / f"{_stamp()}_fatal_{counter}.txt"
        counter += 1

    hint = _hint_for(exc)
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

    body = [
        "=" * 70,
        f"  Fatal error — bot failed to launch / crashed",
        f"  When: {datetime.now().isoformat()}",
        f"  Context: {context or '(startup)'}",
        "=" * 70,
        "",
        f"Python:     {sys.version.splitlines()[0]}",
        f"Executable: {sys.executable}",
        f"Platform:   {platform.platform()}",
        f"CWD:        {Path.cwd()}",
        "",
        f"Exception:  {type(exc).__name__}: {exc}",
        "",
    ]
    if hint:
        body.extend(["Suggested fix:", hint, ""])
    body.extend(["Traceback:", "", tb])

    try:
        path.write_text("\n".join(body), encoding="utf-8")
    except OSError:
        return Path(os.devnull)
    return path
