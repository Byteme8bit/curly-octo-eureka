# 027 — Make the 4h maintenance automation actually ship work

**Requested:** 2026-05-30
**Status:** awaiting verification — pytest passing locally (274), automation
config change pending in the Cursor Automations UI (see below)

## Request
> The scheduled "maintenance" automation (supposed to run every ~4h: review
> crypto news, review the codebase, make tweaks/improvements + tests) "does
> NOTHING AT ALL" — like a developer who shows up every 4 hours, says "nothing
> to do," and leaves. Make it actually make tangible iterations, improvements,
> and tests every cycle, and report what it did to Discord.

## Diagnosis (root cause)

The automation is a **Cursor Automation** (cron trigger) that runs a cloud
agent reading `automation/maintenance_prompt.md` from `main`. It is not
disabled — there are **three** enabled cron automations owned by the user
(one with a `git PR` action, two with no actions). It ran successfully **once**
(2026-05-30 ~16:07–16:16 UTC) and shipped real work — `.gitattributes`,
`docs/logging_conventions.md`, `pytest --cov` in CI, BACKLOG items, feature log
022 (commits `ae6c8fa`, `4e75761`, `469534e`, `562893e`, …). Every run *after*
that produced **zero commits**. The work also never reached `origin/main`
(its tip is `8523fc4`; the `auto/*` commits live only on a branch).

The no-op runs trace to the **prompt itself**, which was passive and
PR-coupled:

1. **GitHub draft PRs were the only delivery path.** The "Failure modes"
   section literally said: *"No GitHub auth in sandbox … skip steps 2/6 and
   just post the report."* So whenever the sandbox can't auth to GitHub
   (likely for the two automations with no `git PR` action), the agent was
   *instructed* to make no changes and only heartbeat.
2. **Pervasive escape hatches.** "Stop early if blocked," a whole "Post when
   nothing was actionable (heartbeat)" template, "If you genuinely can't find
   anything…," "Bail early." Given many low-effort exits, the agent took them.
3. **No mandatory news review.** The user expects a crypto-news pass each run;
   the prompt only had an *optional* market spot-check and never invoked the
   existing `bot/auditor/news_client.py`.
4. **Schedule confusion.** Header said "every 8 hours" while BACKLOG and the
   Discord templates said 4h.

## What changed

### 1. New read-only news CLI — `scripts/review_news.py` (new file)
Thin wrapper over `bot.auditor.news_client.NewsClient`. Prints the top ETH/BTC/
alt headlines (or `--json`). Never raises, always exits 0. Gives the automation
one reliable command for the now-required news-review step.

### 2. Rewrote `automation/maintenance_prompt.md` to be action-biased
- **Prime directive:** every run MUST end with a committed change; "nothing to
  do" is explicitly banned. The *floor* deliverable is a new, specific
  `BACKLOG.md` proposal committed to git — never a bare heartbeat.
- **Required news review (step 2)** via `scripts/review_news.py`, with an
  instruction to tie ≥1 observation/change to it.
- **Delivery fallback ladder (step 6):** Path A draft PR → Path B push branch →
  Path C local commit → Path D commit a backlog proposal. A missing `GH_TOKEN`
  is explicitly *not* an excuse to ship nothing.
- Removed the "ran clean, no changes" heartbeat template; the Discord report
  now must state **reviewed / changed / why / tests / delivery / queued next**.
- Fixed all **8h → 4h** references; kept the off-limits list (strategy logic,
  risk/money constants, `.env`, exchange auth, auto-merge) intact.
- `pytest` must pass before any commit (unchanged, re-emphasised).

### 3. Refreshed `BACKLOG.md`
Moved the three items the first auto-run shipped into **Done** (noting they're
pending merge to `main`), and seeded three concrete, ready-to-implement **Now**
items (stale-state audit + tests, wire the news summary into the auditor
report, add `--cov-fail-under`).

## Files changed
- **New** `scripts/review_news.py` — read-only news-review CLI.
- **New** `feature_logs/027_maintenance-automation-action-bias.md` — this file.
- **Modified** `automation/maintenance_prompt.md` — action-biased rewrite.
- **Modified** `BACKLOG.md` — done/seed refresh.

## Verification
```powershell
.\.venv\Scripts\python.exe -m pytest -q                      # 274 passing
.\.venv\Scripts\python.exe .\scripts\verify_main_startup.py  # SUCCESS
.\.venv\Scripts\python.exe .\scripts\review_news.py --max 5  # prints live headlines
```

## Cursor Automation config — manual step for the user

The prompt fix only takes effect once the automation reads it from `main`, and
the schedule/duplication needs a UI touch (the MCP can read automations but the
stored cron/prompt are redacted, so this can't be safely auto-edited). In the
Cursor **Automations** UI (Sean Lynch's account):

1. **Pick one automation, disable the rest.** Three enabled cron automations
   exist:
   - `d483b346-6791-458c-8d29-f5c8d733ae6d` — has a **git PR** action → keep
     this one as the maintenance agent.
   - `4e72f887-73b7-46e0-9782-f29c9b9ba80b` and
     `793ff41c-6038-4f81-a922-12d26f979c26` — **no actions** (can't open PRs).
     Disable these to stop confusing/duplicate runs.
2. **Set the schedule to every 4 hours:** cron `0 */4 * * *`.
3. **Confirm the prompt points the agent at `automation/maintenance_prompt.md`**
   on `main` (and that this branch's change is merged to `main` first).
4. **Secrets:** add `DISCORD_WEBHOOK` (and `GH_TOKEN` only if `gh` reports auth
   failures in the run log). The Cursor GitHub App usually covers `gh`.
5. After the next run, expect a Discord post in the new format (reviewed /
   changed / why / tests / delivery / queued next) and either a draft PR or an
   `auto/<date>-<slug>` branch/commit.

## Honest note
The prompt is the durable behaviour spec the agent loads each run, but the
*schedule* and *which* automation fires live in the Cursor backend and are
redacted from the MCP read path — so steps 1–4 above must be applied by hand.
Until then, the rewritten prompt won't change behaviour.
