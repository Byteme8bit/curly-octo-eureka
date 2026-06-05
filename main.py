"""Entry point — keeps imports minimal at module load so fatal errors get logged."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is importable when run as `python main.py` from elsewhere
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _run() -> None:
    """All heavy imports live here so missing deps are caught by main()."""
    # Singleton guard must run before any heavy imports so a duplicate is
    # rejected cheaply.  Pass --take-lock when spawned by os.execv restart.
    from bot.singleton import acquire_lock, release_lock

    _take_lock = "--take-lock" in sys.argv
    if _take_lock:
        sys.argv.remove("--take-lock")
    acquire_lock(take_lock=_take_lock)

    import logging
    import signal
    from datetime import datetime

    from bot.engine import TradingEngine
    from bot.local_time import PACIFIC
    from bot.strategies.registry import build_orchestrator
    from config import load_settings

    class PacificFormatter(logging.Formatter):
        def formatTime(self, record, datefmt=None):
            dt = datetime.fromtimestamp(record.created, PACIFIC)
            if datefmt:
                return dt.strftime(datefmt)
            return dt.strftime("%Y-%m-%d %H:%M:%S %Z")

    fmt = PacificFormatter("%(asctime)s [%(levelname)s] %(message)s")
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    log_dir = ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_dir / "runtime.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.WARNING)
    handlers.append(file_handler)
    for handler in handlers:
        handler.setFormatter(fmt)
    logging.basicConfig(level=logging.WARNING, handlers=handlers)

    settings = load_settings()
    strategy = build_orchestrator(settings)
    engine = TradingEngine(settings, strategy)

    def _handle_stop(signum=None, frame=None) -> None:
        engine.shutdown()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _handle_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_stop)

    try:
        if "--test-discord" in sys.argv:
            engine.run_discord_test()
            return
        if "--check-discord" in sys.argv:
            from check_discord import main as check_discord_main
            sys.exit(check_discord_main())
        engine.run()
    except KeyboardInterrupt:
        print("\n  Stopped by user.")
    finally:
        engine.shutdown()
        # Release the lock only on clean exit.  When engine.run() performed a
        # self-restart via os.execv the lock was already claimed by the child
        # process (--take-lock), so we must NOT delete it here.
        if not engine._restart_requested:
            release_lock()


def main() -> None:
    try:
        _run()
    except SystemExit:
        raise
    except KeyboardInterrupt:
        print("\n  Stopped by user.")
    except BaseException as exc:
        # Use the lightweight logger that does not depend on any project module
        from bot.fatal_error_log import log_fatal, _hint_for

        path = log_fatal(exc, context="main startup / runtime")
        print()
        print("=" * 70)
        print(f"  FATAL ERROR: {type(exc).__name__}: {exc}")
        print(f"  Logged to:   {path}")
        hint = _hint_for(exc)
        if hint:
            print()
            print("  Suggested fix:")
            for line in hint.splitlines():
                print(f"    {line}")
        print("=" * 70)
        sys.exit(1)


if __name__ == "__main__":
    main()
