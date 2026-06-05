"""Singleton lock-file guard — prevents duplicate TradeBot instances.

On startup ``acquire_lock()`` is called before any heavy imports.  It writes
the current PID to ``tradebot.lock`` in the repo root.  If a lock file already
exists **and** the recorded PID maps to a live process, the call prints a clear
message and exits with code 1.

Windows ``os.execv`` restart path
----------------------------------
Python's ``os.execv`` on Windows spawns a *child* process instead of replacing
the current one (unlike POSIX).  When the engine performs a self-restart it
therefore passes ``--take-lock`` on the command line so the child process
forcefully claims ownership of the lock rather than seeing the parent's PID and
refusing to start.  The parent (original venv-launcher zombie) either exits
shortly after or is cleaned up by the OS; the lock file already points at the
child by then.

Usage (in main.py)::

    from bot.singleton import acquire_lock, release_lock, LOCK_FILE

    # At the very beginning of _run(), before heavy imports:
    acquire_lock(take_lock="--take-lock" in sys.argv)

    # Remove the flag before engine sees sys.argv:
    if "--take-lock" in sys.argv:
        sys.argv.remove("--take-lock")

    # In the finally block on clean exit (not on restart):
    release_lock()
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

LOCK_FILE: Path = Path(__file__).resolve().parent.parent / "tradebot.lock"


def _pid_is_running(pid: int) -> bool:
    """Return True if a process with *pid* is currently running.

    Uses ``os.kill(pid, 0)`` which works on both POSIX and Windows:
    it raises ``OSError`` (errno ESRCH / ACCESS-DENIED sub-cases) when the
    process does not exist and succeeds silently when it does.
    """
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_lock(*, take_lock: bool = False) -> None:
    """Acquire the singleton PID lock or abort the process.

    Parameters
    ----------
    take_lock:
        When ``True`` the function **overwrites** any existing lock entry with
        the current PID without performing a liveness check.  Pass this flag
        when the process was started via ``os.execv`` restart so the child
        legitimately takes over from the parent.

    Raises / side-effects
    ---------------------
    Calls ``sys.exit(1)`` (does **not** raise) when a live duplicate is found.
    """
    current_pid = os.getpid()

    if not take_lock and LOCK_FILE.exists():
        try:
            raw = LOCK_FILE.read_text(encoding="utf-8").strip()
            recorded_pid = int(raw)
        except (ValueError, OSError):
            recorded_pid = None

        if (
            recorded_pid is not None
            and recorded_pid != current_pid
            and _pid_is_running(recorded_pid)
        ):
            msg = (
                f"\n{'=' * 70}\n"
                f"  DUPLICATE INSTANCE BLOCKED\n"
                f"  TradeBot is already running as PID {recorded_pid}.\n"
                f"  Refusing to start a second instance.\n"
                f"\n"
                f"  Lock file : {LOCK_FILE}\n"
                f"  If the bot is NOT running, delete the lock file and retry:\n"
                f"      del \"{LOCK_FILE}\"\n"
                f"{'=' * 70}\n"
            )
            print(msg, file=sys.stderr)
            sys.exit(1)

    try:
        LOCK_FILE.write_text(str(current_pid), encoding="utf-8")
    except OSError as exc:
        # Non-fatal: warn but don't block startup if the lock file can't be written
        # (e.g. read-only filesystem in CI).
        print(
            f"Warning: could not write singleton lock file {LOCK_FILE}: {exc}",
            file=sys.stderr,
        )


def release_lock() -> None:
    """Remove the PID lock file on clean shutdown.

    Safe to call multiple times; silently ignores a missing file.
    Only call this on clean exit — **not** before a self-restart, so the lock
    stays in place until the child process overwrites it with ``--take-lock``.
    """
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except OSError:
        pass
