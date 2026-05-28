"""Per-file version-history with git-tracked baselines + unified-diff patches.

Stores one folder per source file under `VersionHistory/<rel_path>/` containing:
    - `baseline.<ext>` — the initial full snapshot (captured once)
    - `r<NNN>--<YYYY-MM-DD_HHMMSS>--<slug>.patch` — unified diff from rev N-1 to N
    - `CHANGELOG.md` and `_index.json` live at `VersionHistory/` root.

Public API:
    snapshot(path, reason, *, request_id=None) -> Revision
    list_revisions(path) -> list[Revision]
    reconstruct(path, revision) -> str
    revert(path, revision, *, reason="revert") -> Path
    show_diff(path, revision=None) -> str
    prune_local(*, keep=10) -> dict[str, int]
    auto_snapshot(reason, paths=None, *, request_id=None) -> list[Revision]

Design notes:
- Stays import-light (no ccxt / engine / discord deps) so it can be imported
  by tests and the CLI without spinning up the bot.
- All public functions swallow exceptions and emit warnings to stderr,
  except `revert` which raises if reconstruction fails (data-loss prevention).
- All `VersionHistory/<rel>/` segments use POSIX-style separators so Windows
  backslashes never leak into folder names.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# Constants & helpers
# ---------------------------------------------------------------------------

_PKG_ROOT = Path(__file__).resolve().parent.parent  # project root (../..)
_INDEX_NAME = "_index.json"
_CHANGELOG_NAME = "CHANGELOG.md"
_MAX_REVISION = 999
_SLUG_MAX = 40


def _project_root() -> Path:
    """Project root. Overridable for tests via `BOT_VERSION_HISTORY_PROJECT_ROOT`."""
    override = os.environ.get("BOT_VERSION_HISTORY_PROJECT_ROOT")
    if override:
        return Path(override).resolve()
    return _PKG_ROOT


def _history_root() -> Path:
    """`VersionHistory/` directory. Overridable via `BOT_VERSION_HISTORY_ROOT`."""
    override = os.environ.get("BOT_VERSION_HISTORY_ROOT")
    if override:
        return Path(override).resolve()
    return _project_root() / "VersionHistory"


def _stamp(dt: datetime | None = None) -> str:
    """Compact Pacific timestamp suitable for filenames (`YYYY-MM-DD_HHMMSS`)."""
    try:
        from bot.local_time import pacific_now  # local import keeps module light
        local = pacific_now() if dt is None else dt
    except Exception:  # pragma: no cover - timezone data missing
        local = dt or datetime.now()
    return local.strftime("%Y-%m-%d_%H%M%S")


def _pacific_timestamp() -> str:
    """Human-readable Pacific stamp for CHANGELOG entries."""
    try:
        from bot.local_time import format_pacific
        return format_pacific()
    except Exception:  # pragma: no cover
        return datetime.now().isoformat(timespec="seconds")


def _warn(msg: str) -> None:
    print(f"[version_history] {msg}", file=sys.stderr)


def _slugify(reason: str, max_len: int = _SLUG_MAX) -> str:
    """Kebab-case slug derived from `reason`, ASCII-safe, max `max_len` chars.

    Examples:
        "Fix discord command renames" -> "fix-discord-command-renames"
        "Bug #42 — won't compile!"   -> "bug-42-wont-compile"
    """
    s = unicodedata.normalize("NFKD", reason or "")
    s = s.encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s\-]+", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    if not s:
        s = "edit"
    if len(s) > max_len:
        s = s[:max_len].rstrip("-") or "edit"
    return s


def _rel_path(path: Path) -> Path:
    """Project-relative `Path`. Falls back to filename when outside project root."""
    abs_path = Path(path).resolve()
    try:
        return abs_path.relative_to(_project_root())
    except ValueError:
        return Path(abs_path.name)


def _rel_posix(path: Path) -> str:
    """Project-relative POSIX-style string (used as the key in `_index.json`)."""
    return _rel_path(path).as_posix()


def _file_dir(path: Path) -> Path:
    """`VersionHistory/<rel>/` directory for `path`."""
    return _history_root() / _rel_posix(path)


def _baseline_path(path: Path) -> Path:
    """`baseline.<ext>` path under the file's history dir."""
    suffix = Path(path).suffix
    return _file_dir(path) / f"baseline{suffix}"


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Revision:
    number: int
    path: Path
    timestamp: str
    reason: str
    request_id: str | None
    patch_path: Path
    added: int
    removed: int
    is_noop: bool = False


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _git_show(rel: str) -> str | None:
    """Return `git show HEAD:<rel>` text or `None` if unavailable."""
    try:
        proc = subprocess.run(
            ["git", "show", f"HEAD:{rel}"],
            cwd=str(_project_root()),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


# ---------------------------------------------------------------------------
# Patch generation / application
# ---------------------------------------------------------------------------


def _make_patch(prev: str, curr: str, rel: str) -> tuple[str, int, int]:
    """Generate a unified diff. Returns (patch_text, added_count, removed_count).

    `patch_text` is empty when there is no change.
    """
    prev_lines = prev.splitlines(keepends=True)
    curr_lines = curr.splitlines(keepends=True)
    if not prev_lines and not curr_lines:
        return "", 0, 0
    diff_iter = difflib.unified_diff(
        prev_lines,
        curr_lines,
        fromfile=f"a/{rel}",
        tofile=f"b/{rel}",
        n=3,
        lineterm="\n",
    )
    diff_lines = list(diff_iter)
    added = 0
    removed = 0
    for line in diff_lines:
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    # difflib emits header lines without trailing newlines when lineterm="\n"
    # but actually adds them. Glue lines together exactly as produced.
    patch_text = "".join(
        ln if ln.endswith("\n") else ln + "\n" for ln in diff_lines
    )
    return patch_text, added, removed


_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _apply_patch(source: str, patch_text: str) -> str:
    """Apply a unified-diff `patch_text` to `source`. Returns the new content.

    Pure-Python applier supporting the subset emitted by `difflib.unified_diff`.
    """
    if not patch_text.strip():
        return source
    # Strip everything before the first hunk header
    patch_lines = patch_text.splitlines(keepends=True)
    src_lines = source.splitlines(keepends=True)

    i = 0
    while i < len(patch_lines) and not patch_lines[i].startswith("@@"):
        i += 1

    if i >= len(patch_lines):
        return source  # nothing to apply (e.g. initial-baseline placeholder)

    out: list[str] = []
    src_idx = 0

    while i < len(patch_lines):
        line = patch_lines[i]
        m = _HUNK_RE.match(line)
        if not m:
            raise ValueError(f"malformed hunk header at line {i}: {line!r}")
        orig_start = int(m.group(1))
        # difflib uses 1-based starts; 0 means "empty file"
        target_idx = max(0, orig_start - 1)
        while src_idx < target_idx and src_idx < len(src_lines):
            out.append(src_lines[src_idx])
            src_idx += 1
        i += 1
        while i < len(patch_lines) and not patch_lines[i].startswith("@@"):
            body = patch_lines[i]
            if not body:
                i += 1
                continue
            tag = body[0]
            rest = body[1:]
            if tag == " ":
                if src_idx < len(src_lines):
                    out.append(src_lines[src_idx])
                else:
                    out.append(rest)
                src_idx += 1
            elif tag == "-":
                src_idx += 1
            elif tag == "+":
                out.append(rest)
            elif tag == "\\":
                # "\ No newline at end of file" — strip trailing newline of last out
                if out and out[-1].endswith("\n"):
                    out[-1] = out[-1].rstrip("\n")
            else:
                # Unknown line (e.g. blank between hunks) — ignore
                pass
            i += 1
    while src_idx < len(src_lines):
        out.append(src_lines[src_idx])
        src_idx += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# Index / CHANGELOG
# ---------------------------------------------------------------------------


def _index_path() -> Path:
    return _history_root() / _INDEX_NAME


def _changelog_path() -> Path:
    return _history_root() / _CHANGELOG_NAME


def _load_index() -> dict[str, list[dict]]:
    p = _index_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_index(data: dict[str, list[dict]]) -> None:
    p = _index_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    except OSError as exc:
        _warn(f"failed to write index: {exc}")


def _append_changelog(entry: dict) -> None:
    p = _changelog_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        header_needed = not p.exists()
        with p.open("a", encoding="utf-8") as f:
            if header_needed:
                f.write("# Version history changelog\n\n")
                f.write(
                    "Append-only log. One block per revision per file.\n"
                    "See `bot/version_history.py` for the writer.\n\n"
                )
            f.write(f"## {entry['path']} — r{entry['number']:03d}\n\n")
            f.write(f"- **When:** {entry['timestamp']}\n")
            f.write(f"- **Reason:** {entry['reason']}\n")
            if entry.get("request_id"):
                f.write(f"- **Request:** {entry['request_id']}\n")
            f.write(f"- **Diff:** +{entry['added']} / -{entry['removed']}\n")
            f.write(f"- **Patch:** `{entry['patch']}`\n\n")
    except OSError as exc:
        _warn(f"failed to append changelog: {exc}")


def _append_changelog_note(text: str) -> None:
    p = _changelog_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(f"\n> _{_pacific_timestamp()}_ — {text}\n\n")
    except OSError as exc:
        _warn(f"failed to append changelog note: {exc}")


# ---------------------------------------------------------------------------
# Revision discovery
# ---------------------------------------------------------------------------


_PATCH_RE = re.compile(r"^r(\d{3})--(\d{4}-\d{2}-\d{2}_\d{6})--([a-z0-9\-]+)\.patch$")


def _scan_patch_files(d: Path) -> list[Path]:
    if not d.exists():
        return []
    files = [p for p in d.iterdir() if p.is_file() and _PATCH_RE.match(p.name)]
    files.sort(key=lambda p: int(_PATCH_RE.match(p.name).group(1)))
    return files


def _next_revision_number(d: Path) -> int:
    patches = _scan_patch_files(d)
    if not patches:
        return 1
    last = int(_PATCH_RE.match(patches[-1].name).group(1))
    return last + 1


def _entries_for(path: Path) -> list[dict]:
    rel = _rel_posix(path)
    return _load_index().get(rel, [])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def snapshot(
    path: str | Path,
    reason: str,
    *,
    request_id: str | None = None,
) -> Revision | None:
    """Record a new revision capturing the current on-disk state of `path`.

    Returns the new `Revision`, or the previous one when the diff is empty
    (no-op snapshot). Returns `None` only when something prevents a snapshot
    from being created — a warning is logged in that case.
    """
    src = Path(path)
    try:
        if not src.exists() or src.is_dir():
            _warn(f"cannot snapshot non-file path: {src}")
            return None
        current = src.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        _warn(f"could not read {src}: {exc}")
        return None

    file_dir = _file_dir(src)
    baseline = _baseline_path(src)
    rel = _rel_posix(src)

    try:
        file_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _warn(f"could not create {file_dir}: {exc}")
        return None

    baseline_just_created = False
    is_initial_placeholder = False
    if not baseline.exists():
        baseline_just_created = True
        head_content = _git_show(rel)
        if head_content is not None:
            try:
                baseline.write_text(head_content, encoding="utf-8")
            except OSError as exc:
                _warn(f"could not write baseline: {exc}")
                return None
        else:
            try:
                baseline.write_text(current, encoding="utf-8")
            except OSError as exc:
                _warn(f"could not write baseline: {exc}")
                return None
            is_initial_placeholder = True

    try:
        prev_content = _reconstruct_internal(src)
    except Exception as exc:
        _warn(f"could not reconstruct previous state for {src}: {exc}")
        return None

    if is_initial_placeholder:
        patch_text = (
            f"--- a/{rel}\n"
            f"+++ b/{rel}\n"
            f"# initial baseline - no previous state available\n"
        )
        added = 0
        removed = 0
    else:
        patch_text, added, removed = _make_patch(prev_content, current, rel)
        if not patch_text and prev_content == current:
            if baseline_just_created:
                patch_text = (
                    f"--- a/{rel}\n"
                    f"+++ b/{rel}\n"
                    f"# initial revision - file matches git HEAD\n"
                )
            else:
                patches = _scan_patch_files(file_dir)
                if patches:
                    last_m = _PATCH_RE.match(patches[-1].name)
                    last_num = int(last_m.group(1))
                    entries = _entries_for(src)
                    last_entry = next(
                        (e for e in entries if e["number"] == last_num), None
                    )
                    _append_changelog_note(
                        f"no-op snapshot requested for `{rel}` "
                        f"(reason: {reason!r}) - no change since r{last_num:03d}"
                    )
                    if last_entry:
                        return Revision(
                            number=last_entry["number"],
                            path=src,
                            timestamp=last_entry["timestamp"],
                            reason=last_entry["reason"],
                            request_id=last_entry.get("request_id"),
                            patch_path=file_dir / last_entry["patch"],
                            added=last_entry["added"],
                            removed=last_entry["removed"],
                            is_noop=True,
                        )
                return None

    number = _next_revision_number(file_dir)
    if number > _MAX_REVISION:
        _warn(
            f"revision {number} exceeds max ({_MAX_REVISION}) for {rel} — "
            "prune local patches or archive history"
        )
        return None

    slug = _slugify(reason)
    stamp = _stamp()
    patch_name = f"r{number:03d}--{stamp}--{slug}.patch"
    patch_path = file_dir / patch_name

    try:
        patch_path.write_text(patch_text, encoding="utf-8")
    except OSError as exc:
        _warn(f"could not write patch {patch_path}: {exc}")
        return None

    ts = _pacific_timestamp()
    entry = {
        "number": number,
        "timestamp": ts,
        "reason": reason,
        "request_id": request_id,
        "patch": patch_name,
        "added": added,
        "removed": removed,
        "path": rel,
    }
    index = _load_index()
    index.setdefault(rel, []).append(entry)
    _save_index(index)
    _append_changelog(entry)

    return Revision(
        number=number,
        path=src,
        timestamp=ts,
        reason=reason,
        request_id=request_id,
        patch_path=patch_path,
        added=added,
        removed=removed,
    )


def list_revisions(path: str | Path) -> list[Revision]:
    """All revisions for `path` (oldest first). Returns `[]` if unknown."""
    src = Path(path)
    rel = _rel_posix(src)
    entries = _load_index().get(rel, [])
    file_dir = _file_dir(src)
    out: list[Revision] = []
    for e in entries:
        out.append(
            Revision(
                number=e["number"],
                path=src,
                timestamp=e["timestamp"],
                reason=e["reason"],
                request_id=e.get("request_id"),
                patch_path=file_dir / e["patch"],
                added=e.get("added", 0),
                removed=e.get("removed", 0),
            )
        )
    out.sort(key=lambda r: r.number)
    return out


def _resolve_patch_text(file_dir: Path, rel: str, patch_name: str) -> str | None:
    """Read a patch file locally, or fall back to `git show HEAD:...`."""
    local = file_dir / patch_name
    if local.exists():
        try:
            return local.read_text(encoding="utf-8")
        except OSError:
            pass
    # Best-effort git fallback for pruned patches
    git_rel = f"VersionHistory/{rel}/{patch_name}"
    return _git_show(git_rel)


def _reconstruct_internal(path: Path, revision: int | None = None) -> str:
    """Reconstruct content at revision N (default: last known). Empty if no baseline."""
    src = Path(path)
    rel = _rel_posix(src)
    file_dir = _file_dir(src)
    baseline = _baseline_path(src)
    if not baseline.exists():
        return ""
    content = baseline.read_text(encoding="utf-8", errors="replace")
    entries = _load_index().get(rel, [])
    if not entries:
        return content
    entries = sorted(entries, key=lambda e: e["number"])
    target = revision if revision is not None else entries[-1]["number"]
    for e in entries:
        if e["number"] > target:
            break
        patch_text = _resolve_patch_text(file_dir, rel, e["patch"])
        if patch_text is None:
            raise FileNotFoundError(
                f"patch r{e['number']:03d} for {rel} is not available locally "
                f"or via git history"
            )
        content = _apply_patch(content, patch_text)
    return content


def reconstruct(path: str | Path, revision: int) -> str:
    """Reproduce file content as of revision N. Returns "" if no history."""
    try:
        return _reconstruct_internal(Path(path), revision)
    except Exception as exc:
        _warn(f"reconstruct failed for {path} r{revision}: {exc}")
        return ""


def show_diff(path: str | Path, revision: int | None = None) -> str:
    """Unified diff between revision N (default: latest) and the current file."""
    src = Path(path)
    try:
        if not src.exists():
            return ""
        current = src.read_text(encoding="utf-8", errors="replace")
        entries = _load_index().get(_rel_posix(src), [])
        if not entries:
            return ""
        target = revision if revision is not None else max(e["number"] for e in entries)
        prev = _reconstruct_internal(src, target)
        rel = _rel_posix(src)
        diff = difflib.unified_diff(
            prev.splitlines(keepends=True),
            current.splitlines(keepends=True),
            fromfile=f"a/{rel}@r{target:03d}",
            tofile=f"b/{rel}@current",
            n=3,
            lineterm="\n",
        )
        return "".join(ln if ln.endswith("\n") else ln + "\n" for ln in diff)
    except Exception as exc:
        _warn(f"show_diff failed: {exc}")
        return ""


def revert(path: str | Path, revision: int, *, reason: str = "revert") -> Path:
    """Restore `path` to revision N. Snapshots current state first as a backup.

    Raises if reconstruction fails — we never want to overwrite a working file
    with garbage. Returns the path on success.
    """
    src = Path(path)
    if not src.exists():
        raise FileNotFoundError(src)

    backup_reason = f"pre-revert backup (target=r{revision:03d}: {reason})"
    snapshot(src, backup_reason, request_id=None)

    content = _reconstruct_internal(src, revision)
    if not content and revision > 0:
        raise RuntimeError(
            f"reconstruction returned empty content for {src} r{revision} — "
            "aborting revert to avoid data loss"
        )
    src.write_text(content, encoding="utf-8")
    return src


def prune_local(*, keep: int = 10) -> dict[str, int]:
    """Delete local patch files older than the last `keep` per file.

    Baselines are never deleted. Patches removed locally remain recoverable
    via git history. Returns `{rel_path: deleted_count}`.
    """
    if keep < 0:
        _warn("prune_local: keep must be >= 0")
        return {}
    root = _history_root()
    if not root.exists():
        return {}

    deleted_map: dict[str, int] = {}
    for rel, entries in _load_index().items():
        file_dir = root / rel
        patches = _scan_patch_files(file_dir)
        if len(patches) <= keep:
            continue
        to_delete = patches[: len(patches) - keep]
        count = 0
        for p in to_delete:
            try:
                p.unlink()
                count += 1
            except OSError as exc:
                _warn(f"could not prune {p}: {exc}")
        if count:
            deleted_map[rel] = count
    if deleted_map:
        total = sum(deleted_map.values())
        _append_changelog_note(
            f"pruned local patches: kept last {keep} per file, deleted {total} "
            f"across {len(deleted_map)} file(s) (recoverable via git history)"
        )
    return deleted_map


def auto_snapshot(
    reason: str,
    paths: Iterable[str | Path] | None = None,
    *,
    request_id: str | None = None,
) -> list[Revision]:
    """Convenience: snapshot a set of paths in one call. Returns successful revisions."""
    results: list[Revision] = []
    if not paths:
        return results
    for p in paths:
        rev = snapshot(p, reason, request_id=request_id)
        if rev is not None:
            results.append(rev)
    return results


def verify_all() -> tuple[int, list[str]]:
    """Reconstruct every tracked file's full history. Returns (ok_count, errors)."""
    ok = 0
    errors: list[str] = []
    for rel, entries in _load_index().items():
        path = _project_root() / rel
        try:
            for e in sorted(entries, key=lambda x: x["number"]):
                _reconstruct_internal(path, e["number"])
            ok += 1
        except Exception as exc:
            errors.append(f"{rel}: {exc}")
    return ok, errors
