# 054 — Auditor Discord UX (forecast, news, proposals, attachments)

**Requested:** 2026-06-14
**Status:** awaiting verification — pytest pending

## Request

A–E improvements on Auditor / Discord after PR #51 (dual PnL, kraken-prop.md):

- **A** Forecast clarity — explicit confidence + bootstrap labels
- **B** News — clickable URLs + rule-based strategy impact lines
- **C** Proposal UX — batch confirm, conflict detection, overload warnings
- **D** Full audit report as `.txt` Discord attachment
- **E** Document Trade Prop $5k as unsupported (no fake integration)

## Actions taken

- `bot/auditor/report.py` — forecast confidence/method labels, news impact heuristics,
  proposal overload block, `prepare_report_attachment()`
- `bot/auditor/proposer.py` — `knobs_with_conflicts`, `dedupe_proposals_by_knob`
- `bot/auditor/state.py` — replace same-knob pending on new audit
- `bot/auditor_service.py` — batch confirm (`all`, comma IDs), attachment post,
  auto-apply skips conflicting pending knobs, help text
- `bot/discord_bot.py` — `post_with_attachment` multipart upload; help text
- `tests/test_auditor.py` — forecast formatting, news URLs/impact, conflicts, batch confirm

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_auditor.py -v
```

Restart TradeBot after merge: quit `main.py` and relaunch so Discord + auditor pick up changes.

## Notes

- Kraken Trade Prop remains documented in `docs/kraken-prop.md` only — spot wallet live mode is unchanged.
- Attachment cap 8MB; truncated files note full path on disk.
