# AGENTS.md

Conventions for any AI agent (Cursor, Codex, Claude Code, etc.) working in
this repo. Mirrors the `.cursor/rules/` set so non-Cursor tools see the same
protocols.

## Version history protocol

At the end of every request that **modifies existing files** (not new ones),
record one snapshot per modified file:

```powershell
.\.venv\Scripts\python.exe scripts\version_history.py snapshot <path> --reason "<short summary>" --request-id <feature_log_id>
```

- One snapshot per file per request batch (not one per individual edit).
- Skip newly-created files — they have no prior baseline.
- Always include `--request-id` matching the feature-log number (e.g. `013`)
  so `VersionHistory/CHANGELOG.md` cross-references neatly.
- If the user asks for a revert, use:
  ```powershell
  .\.venv\Scripts\python.exe scripts\version_history.py revert <path> --rev N --reason "<why>"
  ```
  The CLI auto-snapshots current state first as a `pre-revert backup`
  revision before overwriting the file.
- `VersionHistory/` is tracked in git. To save local disk space, run
  `prune-local --keep 10` periodically; older patches stay in git history.

See `bot/version_history.py` for the implementation and
`.cursor/rules/version-history.mdc` for the rule loaded by Cursor.

## Fatal-error logging

Crashes at startup are captured to `Error Logs/` by `bot/fatal_error_log.py`.
See `feature_logs/011_fatal-error-logging.md`.

## Feature logs

Every user-driven feature request gets a numbered markdown file in
`feature_logs/` — see `feature_logs/README.md` for the template.

## Verification convention

The Cursor agent's shell is sandbox-locked on this machine, so it cannot run
`pytest` or `python main.py`. Whenever a request needs verification, leave
the feature-log status as `awaiting verification - pytest pending` and list
the exact commands the user should run.
