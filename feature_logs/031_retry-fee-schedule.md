# 031 — Retry fee schedule after transient failures

**Requested:** 2026-05-31 04:03 PDT
**Status:** complete

## Request
Deep bug-finding automation: inspect recent commits for high-severity correctness bugs, fix only concrete critical issues, and report bug/impact, root cause, fix, and validation.

## Actions taken
- Investigated recent runtime changes for watchdog alerting, auditor chat/state, automation alerts, and Kraken fee/market monitoring.
- Fixed `bot/fee_engine.py` so a transient Kraken fee-schedule failure no longer pins env-default fees for the life of the process. The fallback path no longer marks the schedule loaded, and fallback fees are cached only for `schedule_retry_sec` so the engine recovers automatically once connectivity returns.
- Cleared cached fallback symbol fees once a real schedule loads.
- Added regression coverage in `tests/test_fee_engine.py` for recovery after an initial public fee-schedule outage.

## Verification
- `pytest tests/test_fee_engine.py`
- `pytest`

## Notes
- Originally authored as request 022 (PR #20); renumbered to 031 on merge because the 022 slot was taken by `022_auditor-chat-nameerror-fix.md` after this branch was cut. The fix composes cleanly with the later `force_static` override (request 026): `force_static` short-circuits before the schedule logic, so the retry path only applies to live-fee mode (`FEE_FORCE_STATIC=0`).
- Watchdog alert delivery also has reliability risk under Discord outages, but the runtime-log file offset path needs a durable retry-queue design to fully address single-event delivery loss. The fee-schedule issue has a narrower, high-confidence fix.
