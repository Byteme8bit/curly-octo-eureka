# 032 — Maintenance automation: junior+senior review loop

**Requested:** 2026-06-01
**Status:** awaiting verification — pytest passing locally (305); PR opened as a
draft for senior (human/parent) review, not merged.

## Request
> The 4-hour maintenance automation is now the user's ONLY automation and must
> embody a junior+senior developer workflow. Every run should:
> 1. act as BOTH roles — first a JUNIOR dev (investigate + draft/implement a
>    concrete improvement), then a SENIOR dev who self-reviews that work for
>    correctness, safety, scope, and test coverage *before* opening the PR
>    (PR description carries the senior-review notes); still no auto-merge;
> 2. review all five inputs each run — source code, runtime logs
>    (`logs/runtime.log` + the 4h window logs), past trades (`receipts/` +
>    the trade log), current/past market performance (`paper_portfolio.json`
>    + logged snapshots), and the current/past day of crypto news
>    (`scripts/review_news.py` / `bot/auditor/news_client.py`);
> 3. target improvements across ALL THREE subsystems over time — TradeBot,
>    WatchDog, Auditor — rotating focus so none is neglected.
>
> Preserve the action-bias, the delivery fallback ladder, the rich Discord
> report, the off-limits guardrails, and the 4h cadence. Refine, don't gut.

## Actions taken
- **Modified** `automation/maintenance_prompt.md` (refined, not rewritten):
  - **Role** reframed as a single run wearing **both hats**: JUNIOR (review +
    draft/implement with tests) then SENIOR (self-review before the PR). Kept
    the prime directive ("nothing to do" banned) verbatim in intent.
  - Added a **"three subsystems — rotate your focus"** section mapping
    TradeBot / WatchDog / Auditor to concrete files, with an instruction to
    prefer the subsystem that has gone longest without attention.
  - Consolidated the old steps 2–4 (news / triage / live-bot) into a single
    **step 2 "Review the five inputs — as the JUNIOR dev (REQUIRED)"** covering
    (a) source code, (b) runtime logs + 4h windows, (c) past trades
    (`receipts/` + window logs), (d) market performance (`paper_portfolio.json`
    + snapshot trend), (e) current + past-day crypto news. PR triage, auditor
    state, and Kraken checks folded in. News step stays required and read-only.
  - **Step 3** now "Pick *and implement* the improvement (junior)" with a
    subsystem-rotation tie-breaker; kept the priority ladder, the floor
    backlog-proposal deliverable, allow-list, and off-limits guardrails intact.
  - **New step 4 "Self-review the change — as the SENIOR dev (before any PR)"**:
    a correctness / safety-scope / test-coverage / risks-rollback checklist
    whose answers feed the PR body. Still never merges.
  - **Step 5 "Deliver"** preserves the Path A→D fallback ladder; Path A PR body
    template now includes a structured **"Senior review"** section + subsystem.
  - **Step 6 Discord** and **step 7 run report** templates extended with
    Subsystem, the five review inputs, and a Senior-review line.
  - Renumbered all internal step references and the failure-modes / config
    sections to match the new 7-step flow.
- **Preserved intact:** action-bias / "nothing to do" ban, the delivery
  fallback ladder (draft PR → push branch → local commit → BACKLOG floor), the
  rich Discord report, the off-limits guardrails (no strategy/risk/money
  constants, `.env`, exchange auth, existing auditor chat handlers; never
  auto-merge), and the 4-hour cadence.

## Files changed
- **Modified** `automation/maintenance_prompt.md` — junior+senior dual-role
  refinement.
- **New** `feature_logs/032_maintenance-junior-senior-review-loop.md` — this file.

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest -q     # 305 passing
```
Docs/prompt-only change; no runtime code touched. PR left **open as a draft**
for the senior reviewer (human/parent) — not merged.

## Notes
- A live bot (PID 151108) was running during this change; only the tracked
  prompt + feature log were touched. No state files, `.env`, or process were
  disturbed.
