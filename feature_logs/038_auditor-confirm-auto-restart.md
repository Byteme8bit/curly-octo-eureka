# 038 — Auditor confirm auto-restart

**Requested:** 2026-06-08
**Status:** complete

## Request

When the user confirms an auditor proposal in Discord (`Auditor -confirm <id>`), the bot should automatically restart to load the new `runtime_overrides.json` value — using the same safe self-restart path as overnight auto-apply (`request_restart` → shutdown → `os.execv` with `--take-lock`).

## Actions taken

- `bot/auditor_service.py` — after a successful `confirm_proposal` apply, call `request_restart()` when `confirm_restart_enabled` is on; Discord reply says "Restarting bot to load new settings…". Failed/expired confirms do not restart.
- `bot/auditor/config.py` — added `confirm_restart_enabled` (default True).
- `config.py` — `auditor_confirm_restart_enabled` from `AUDITOR_CONFIRM_RESTART` (default `1`).
- `bot/engine.py` — wire new setting into `AuditorConfig`.
- `.env.example` — documented `AUDITOR_CONFIRM_RESTART=1`.
- `tests/test_auditor.py` — confirm success schedules restart (mocked); failure and disabled-flag paths do not.

## Verification

- `pytest` green on auditor confirm restart tests.
- Manual: `Auditor -confirm <id>` on a pending proposal should reply with restart notice and process should come back with override loaded.

## Notes

- Disable with `AUDITOR_CONFIRM_RESTART=0` if you want the old manual-restart behaviour.
- Uses existing `--take-lock` singleton path so Windows `os.execv` child is not blocked by the parent's lock file.
