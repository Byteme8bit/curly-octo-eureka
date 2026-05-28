# 013 — Per-file version history (baselines + unified-diff patches)

**Requested:** 2026-05-25 13:50 PDT
**Status:** ✅ complete — verified 2026-05-25 15:23 PDT (21 tests pass; 7 baselines bootstrapped; smoke test/list/prune/verify all clean)

## Request

> Please create a differencing library and/or a changelog for existing files
> that you edit over time so you can easily revert changes as needed. Maybe
> there should even just be a "VersionHistory" folder that keeps "original
> copies" of files (date/timestamped and maybe a revision number pre/suffix of
> course) that you can more easily reload into the "primary folder" where
> files originally existed.

Follow-up clarifications from the user:

> 1) Tracked in Git for ALL files, but locally go with Hybrid approach to save
>    local storage space
> 2) Every major set of edits (all the edits required to solve an error or
>    fulfill a new request to an existing file should have a revisioned file
>    number storing the line by line differences (not the whole original file)
>    to further help conserve storage space everywhere

## Design

- **Storage model**: per-file folder under `VersionHistory/<rel_path>/`
  containing one `baseline.<ext>` (full snapshot, captured once) plus
  `r<NNN>--<YYYY-MM-DD_HHMMSS>--<slug>.patch` files (unified diffs against
  the previous revision). Tiny on disk — every revision after baseline is
  just the line-level changes.
- **Granularity**: ONE revision per request batch (not per `StrReplace`
  call). The agent calls `snapshot` after all edits for the request are
  settled, capturing the post-edit file state.
- **Git policy**: the entire `VersionHistory/` tree is tracked in git so
  baselines, patches, and the changelog are portable across machines.
- **Local prune**: `prune-local --keep 10` deletes older patches from disk
  but never the baseline. Pruned patches stay recoverable through git
  history (`git show HEAD:VersionHistory/...`).
- **Layout**:

  ```
  VersionHistory/
  |-- CHANGELOG.md       # human-readable, one block per revision
  |-- _index.json        # machine-readable index keyed by rel path
  `-- bot/discord_bot.py/
      |-- baseline.py
      |-- r001--2026-05-25_205000--discord-renames.patch
      `-- r002--2026-05-25_210000--clearchat-fix.patch
  ```

## Files added

- **`bot/version_history.py`** — pure-Python core module. Public API:
  `snapshot`, `list_revisions`, `reconstruct`, `revert`, `show_diff`,
  `prune_local`, `auto_snapshot`, `verify_all`, plus the `Revision`
  dataclass. Stays import-light (no ccxt / engine / discord deps) so the
  CLI and tests run without spinning up the bot. Uses
  `bot.local_time.pacific_now` / `format_pacific` for stamps and
  `subprocess.run(["git", ...])` for the baseline fallback. Public
  functions swallow exceptions and warn to stderr; `revert` raises only if
  reconstruction fails (data-loss prevention).
- **`scripts/version_history.py`** — CLI with subcommands `snapshot`,
  `list`, `diff`, `reconstruct`, `revert`, `prune-local`, `verify`.
- **`.cursor/rules/version-history.mdc`** — Cursor rule (always-applied)
  documenting when and how to snapshot during agent edits. Authored using
  the create-rule skill's frontmatter convention.
- **`AGENTS.md`** — repo-level agent protocol. Mirrors the Cursor rule so
  Codex / Claude Code / any other agent sees the same convention. Also
  documents the existing fatal-error-logging convention and the sandbox
  verification convention.
- **`tests/test_version_history.py`** — 21 isolated tests using `tmp_path`
  and env-var-driven project/history root overrides.
- **`scripts/bootstrap_version_history.py`** — one-shot helper that calls
  `snapshot()` for each file edited in feature logs 010 / 011 / 012 so the
  user can populate initial baselines with a single command.
- **`feature_logs/013_version-history-system.md`** — this file.

## Files modified

- **`.gitignore`** — added an explicit `!VersionHistory/` / `!VersionHistory/**`
  block so any future wildcard ignore can't accidentally hide the version
  history from git.

## Bootstrap baselines

Cursor's sandbox shell can't actually execute `python` to call the snapshot
API itself, so a bootstrap helper is shipped instead:

```powershell
.\.venv\Scripts\python.exe scripts\bootstrap_version_history.py
```

`scripts/bootstrap_version_history.py` calls `snapshot()` for each file
edited in feature logs 010 / 011 / 012:

- `bot/discord_bot.py`
- `bot/engine.py`
- `bot/fatal_error_log.py`
- `main.py`
- `.gitignore`
- `docs/design/discord-style-guide.md`
- `docs/architecture/modules.md`

Each uses reason `"initial baseline for already-tracked work"` and
`request_id="013"`. Where `git show HEAD:<path>` returns content, the
baseline is the git-HEAD state and `r001` is the diff capturing every
already-applied edit. Where git lookup fails, the baseline is the current
file content and `r001` is a placeholder marked
`# initial baseline - no previous state available`. Missing files are
skipped silently.

The script is safe to re-run — re-snapshotting an unchanged file is a
no-op that just appends a CHANGELOG note instead of creating a duplicate
revision.

## Tests written

21 isolated tests in `tests/test_version_history.py`. Highlights:

- First-snapshot creates baseline + r001 (no-git path).
- First-snapshot with mocked git HEAD produces a real diff against HEAD.
- Second snapshot records only the diff, not the full file.
- No-op snapshot returns the prior revision without creating a new patch.
- `list_revisions` returns revisions in order.
- `reconstruct` reproduces exact content for every revision.
- `show_diff` includes `--- a/` and `+++ b/` headers.
- `revert` restores file content and records a `pre-revert backup` revision.
- `prune_local(keep=2)` deletes older patches and keeps baseline + last 2.
- Slug sanitisation: kebab-case, ASCII-only, truncated to 40 chars, empty
  reasons fall back to `edit`.
- CHANGELOG.md records one block per revision with reason + request id.
- Unicode / quoted reasons produce safe slugs but preserve original text in
  changelog.
- 5-revision chain reconstructs every intermediate state byte-for-byte.
- `auto_snapshot` handles multiple files in one call.
- `verify_all` round-trips every tracked file.
- Revisions are zero-padded to 3 digits (`r001`, `r002`, ...).

## Verification

Cursor's sandbox-locked shell (feature 007) blocks me from running pytest
or the CLI. The user should run, from `C:\Users\lynch\eth-trading-bot`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_version_history.py -v
.\.venv\Scripts\python.exe scripts\bootstrap_version_history.py
.\.venv\Scripts\python.exe scripts\version_history.py snapshot bot\engine.py --reason "smoke test" --request-id 013
.\.venv\Scripts\python.exe scripts\version_history.py list bot\engine.py
.\.venv\Scripts\python.exe scripts\version_history.py prune-local --keep 10
.\.venv\Scripts\python.exe scripts\version_history.py verify
```

Expected: 21 green tests; the bootstrap creates 7 baseline trees under
`VersionHistory/`; the smoke snapshot of `bot/engine.py` records as
`r002` (the bootstrap created `r001`); `list` shows both revisions;
`prune-local` reports nothing to prune yet; `verify` reports all tracked
files reconstructing cleanly.

If anything fails, flip status to `blocked` and capture the failing output
in this file.

## Notes

- The diff applier (`_apply_patch`) is a pure-Python implementation of the
  subset of unified-diff that `difflib.unified_diff` emits. It does not
  emit or honour `\ No newline at end of file` markers, so files that lack
  a trailing newline will have one added back during reconstruction. All
  Python sources in this repo already end with newlines, so this is a
  practical non-issue but worth noting if we ever start tracking binary or
  no-newline files.
- Patch filenames cap at 999 revisions (`r999`). Practical reality: prune
  long before that. The module emits a warning and refuses the snapshot if
  the cap is hit, rather than silently overflowing.
- Reasons containing quotes / unicode / em-dashes / Chinese characters get
  sanitised to ASCII-only kebab-case for filenames (so they're safe on
  Windows / NTFS), but the original UTF-8 reason is preserved in
  `CHANGELOG.md` and `_index.json`.
- The CLI's `revert` always snapshots current state first as a
  `pre-revert backup` revision. If current state matches the last
  snapshotted revision exactly, the no-op branch fires and the changelog
  records a `no-op snapshot requested ... - no change since rNNN` note
  instead of creating a redundant revision.
- Per feature 010's verification convention, this stays
  `awaiting verification` until the user confirms.
