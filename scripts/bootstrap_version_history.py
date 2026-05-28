"""One-shot bootstrap: capture initial baselines for already-edited files.

Run this once after merging feature 013. It calls
``bot.version_history.snapshot`` for each file in the bootstrap list and
records a single revision (``r001``) per file, tagged
``request_id="013"`` and reason
``"initial baseline for already-tracked work"``.

If `git show HEAD:<path>` succeeds (the file is in git), the baseline is
the git-HEAD content and ``r001`` is the diff against the current file
state. If git isn't usable, the baseline is the current file content and
``r001`` is the placeholder patch noting
``# initial baseline - no previous state available``.

Files that don't exist are skipped silently.

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\bootstrap_version_history.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot import version_history as vh  # noqa: E402

BOOTSTRAP_FILES: list[str] = [
    "bot/discord_bot.py",
    "bot/engine.py",
    "bot/fatal_error_log.py",
    "main.py",
    ".gitignore",
    "docs/design/discord-style-guide.md",
    "docs/architecture/modules.md",
]

REASON = "initial baseline for already-tracked work"
REQUEST_ID = "013"


def main() -> int:
    captured = 0
    skipped: list[str] = []
    noop: list[str] = []
    for rel in BOOTSTRAP_FILES:
        abs_path = ROOT / rel
        if not abs_path.exists():
            skipped.append(rel)
            print(f"  skip:    {rel} (not found)")
            continue
        rev = vh.snapshot(abs_path, REASON, request_id=REQUEST_ID)
        if rev is None:
            print(f"  failed:  {rel} (could not snapshot)")
            continue
        if rev.is_noop:
            noop.append(rel)
            print(f"  no-op:   {rel} (already at r{rev.number:03d})")
            continue
        captured += 1
        print(
            f"  captured {rel} -> r{rev.number:03d} "
            f"(+{rev.added}/-{rev.removed})"
        )

    print()
    print(f"Bootstrap complete: {captured} new baselines, "
          f"{len(noop)} already tracked, {len(skipped)} skipped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
