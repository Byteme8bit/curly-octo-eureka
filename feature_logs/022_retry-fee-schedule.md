# 022 — Retry fee schedule after transient failures

**Requested:** 2026-05-31 04:03 PDT
**Status:** in progress

## Request
Deep bug-finding automation: inspect recent commits for high-severity correctness bugs, fix only concrete critical issues, and report bug/impact, root cause, fix, and validation.

## Actions taken
- Investigated recent runtime changes for watchdog alerting, auditor chat/state, automation alerts, and Kraken fee/market monitoring.
- Fixed `bot/fee_engine.py` so a transient Kraken fee-schedule failure no longer pins env-default fees for the life of the process.
- Added regression coverage in `tests/test_fee_engine.py` for recovery after an initial public fee-schedule outage.

## Verification
- Pending.

## Notes
- Watchdog alert delivery also has reliability risk under Discord outages, but the runtime-log file offset path needs a durable retry-queue design to fully address single-event delivery loss. The fee-schedule issue has a narrower, high-confidence fix.
