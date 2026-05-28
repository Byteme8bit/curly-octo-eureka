"""Command-line wrapper around `bot.version_history`.

Subcommands:
    snapshot      record a new revision for a file
    list          list revisions for a file (or all files)
    diff          show diff between a revision and current file content
    reconstruct   print or write the content of a specific revision
    revert        restore a file to a previous revision (auto-backups first)
    prune-local   delete older patches locally (keeping last N per file)
    verify        reconstruct every revision of every file - sanity check

Typical usage (PowerShell):
    .\\.venv\\Scripts\\python.exe scripts\\version_history.py snapshot bot\\engine.py --reason "fix ws reconnect" --request-id 014
    # Multiple files share one --reason / --request-id:
    .\\.venv\\Scripts\\python.exe scripts\\version_history.py snapshot bot\\engine.py bot\\auditor_service.py --reason "auto-apply" --request-id 020
    .\\.venv\\Scripts\\python.exe scripts\\version_history.py list bot\\engine.py
    .\\.venv\\Scripts\\python.exe scripts\\version_history.py diff bot\\engine.py --rev 2
    .\\.venv\\Scripts\\python.exe scripts\\version_history.py revert bot\\engine.py --rev 2 --reason "ws change broke watcher"
    .\\.venv\\Scripts\\python.exe scripts\\version_history.py prune-local --keep 10
    .\\.venv\\Scripts\\python.exe scripts\\version_history.py verify
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot import version_history as vh  # noqa: E402


def _cmd_snapshot(args: argparse.Namespace) -> int:
    """Snapshot one or more files in a single invocation.

    Shares ``--reason`` and ``--request-id`` across every path. Per-file
    failures don't abort the batch; the exit code is non-zero if any file
    failed entirely (vh.snapshot returned None).
    """
    failures = 0
    for path in args.paths:
        rev = vh.snapshot(path, args.reason, request_id=args.request_id)
        if rev is None:
            print(f"No snapshot recorded for {path} (file missing or write failure).")
            failures += 1
            continue
        if rev.is_noop:
            print(
                f"No changes — previous revision is r{rev.number:03d} for {rev.path}\n"
                f"  reason:  {rev.reason}\n"
                f"  request: {rev.request_id or '-'}\n"
                f"  patch:   {rev.patch_path}"
            )
            continue
        print(
            f"Recorded r{rev.number:03d} for {rev.path} (+{rev.added}/-{rev.removed})\n"
            f"  reason:  {rev.reason}\n"
            f"  request: {rev.request_id or '-'}\n"
            f"  patch:   {rev.patch_path}"
        )
    return 1 if failures else 0


def _cmd_list(args: argparse.Namespace) -> int:
    if args.path:
        revs = vh.list_revisions(args.path)
        if not revs:
            print(f"No revisions tracked for {args.path}.")
            return 0
        print(f"Revisions for {args.path} ({len(revs)} total):")
        for r in revs:
            req = f" [req={r.request_id}]" if r.request_id else ""
            print(
                f"  r{r.number:03d}  {r.timestamp}  +{r.added}/-{r.removed}  "
                f"{r.reason}{req}"
            )
        return 0

    index = vh._load_index()  # noqa: SLF001
    if not index:
        print("No files tracked yet.")
        return 0
    print(f"Tracked files: {len(index)}")
    for rel, entries in sorted(index.items()):
        last = max(entries, key=lambda e: e["number"]) if entries else None
        if last:
            print(
                f"  {rel:<60} {len(entries):>3} rev(s)  "
                f"latest=r{last['number']:03d} ({last['timestamp']})"
            )
        else:
            print(f"  {rel:<60}  (no revisions)")
    return 0


def _cmd_diff(args: argparse.Namespace) -> int:
    text = vh.show_diff(args.path, args.rev)
    if not text:
        print(f"No diff (no history for {args.path} or file unchanged).")
        return 0
    sys.stdout.write(text)
    if not text.endswith("\n"):
        sys.stdout.write("\n")
    return 0


def _cmd_reconstruct(args: argparse.Namespace) -> int:
    text = vh.reconstruct(args.path, args.rev)
    if not text:
        print(
            f"Could not reconstruct {args.path} at r{args.rev:03d} "
            f"(no history or patches missing).",
            file=sys.stderr,
        )
        return 1
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Wrote reconstructed r{args.rev:03d} of {args.path} -> {args.out}")
        return 0
    sys.stdout.write(text)
    if not text.endswith("\n"):
        sys.stdout.write("\n")
    return 0


def _cmd_revert(args: argparse.Namespace) -> int:
    try:
        path = vh.revert(args.path, args.rev, reason=args.reason)
    except Exception as exc:  # noqa: BLE001
        print(f"Revert failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"Reverted {path} to r{args.rev:03d}. "
        "A pre-revert backup snapshot was recorded - run `list` to see it."
    )
    return 0


def _cmd_prune(args: argparse.Namespace) -> int:
    deleted = vh.prune_local(keep=args.keep)
    if not deleted:
        print(f"Nothing to prune (kept up to {args.keep} per file).")
        return 0
    total = sum(deleted.values())
    print(f"Pruned {total} patch file(s) across {len(deleted)} tracked file(s):")
    for rel, count in sorted(deleted.items()):
        print(f"  {rel}: removed {count}")
    print("Older patches remain recoverable via `git show`.")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    ok, errors = vh.verify_all()
    if errors:
        print(f"Verified {ok} file(s); {len(errors)} error(s):")
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(f"All {ok} tracked file(s) reconstruct cleanly.")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="VersionHistory CLI - per-file revision tracking",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_snap = sub.add_parser(
        "snapshot",
        help="record a revision of one or more files (shares --reason/--request-id)",
    )
    p_snap.add_argument("paths", nargs="+", help="one or more file paths to snapshot")
    p_snap.add_argument("--reason", required=True)
    p_snap.add_argument("--request-id", default=None)
    p_snap.set_defaults(func=_cmd_snapshot)

    p_list = sub.add_parser("list", help="list revisions for a file (or all)")
    p_list.add_argument("path", nargs="?")
    p_list.set_defaults(func=_cmd_list)

    p_diff = sub.add_parser("diff", help="show diff between a revision and current")
    p_diff.add_argument("path")
    p_diff.add_argument("--rev", type=int, default=None)
    p_diff.set_defaults(func=_cmd_diff)

    p_recon = sub.add_parser("reconstruct", help="print or write content at revision N")
    p_recon.add_argument("path")
    p_recon.add_argument("--rev", type=int, required=True)
    p_recon.add_argument("--out", default=None, help="optional output path")
    p_recon.set_defaults(func=_cmd_reconstruct)

    p_rev = sub.add_parser("revert", help="restore a file to a previous revision")
    p_rev.add_argument("path")
    p_rev.add_argument("--rev", type=int, required=True)
    p_rev.add_argument("--reason", default="manual revert")
    p_rev.set_defaults(func=_cmd_revert)

    p_prune = sub.add_parser("prune-local", help="delete older local patches")
    p_prune.add_argument("--keep", type=int, default=10)
    p_prune.set_defaults(func=_cmd_prune)

    p_ver = sub.add_parser("verify", help="reconstruct everything as a sanity check")
    p_ver.set_defaults(func=_cmd_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
