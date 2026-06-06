# Backlog

Curated list of improvements for TradeBot. The 4-hour maintenance agent
(see `automation/maintenance_prompt.md`) reads this first when deciding
what to work on.

## How to use this file

- **User** adds items they want done but can't get to. Sketch what + why,
  one bullet each, doesn't have to be precise — the agent will figure out
  the details.
- **Agent** picks unchecked items, ships them as draft PRs, marks them
  done in the same PR (`- [x]`). When new ideas surface during a run,
  add them here for future runs.
- Items below the `---` line are agent-seeded; the user can promote them
  upward or delete them.
- Move done items to the bottom under "Done" with the PR number, so the
  list stays scannable.

---

## Now (next 1-3 runs)

- [x] **Detect other "stale-state-on-disk" patterns.** Shipped #041 —
  `RiskState.from_dict()` now clears expired `paused_until` on load;
  regression tests added for all three files.
- [x] **Surface the news review in the auditor report.** Shipped #042 —
  `render_markdown_report()` now cites 1–2 ETH/BTC headlines in the
  "Headline numbers" section.
- [x] **Pin a minimum coverage threshold now that `pytest --cov` runs in CI.**
  Shipped #038 — `pytest-cov>=5.0.0` in `requirements-dev.txt`; CI now runs
  `--cov=bot --cov-fail-under=53` (current: 54.32%).

## Soon (anytime)

- [x] **Centralise the Discord webhook posting logic.** Shipped #039 —
  `bot/notifications/discord_webhook.py` with `post_webhook()` / `post_alert()`;
  both scripts refactored to one-liners.
- [ ] **`bot/auditor_service.py` is 600+ lines.** Worth splitting the
  proposal-application path from the chat path. Only do this after
  test coverage exists for the parts you'd extract.
- [x] **Add observability counters for triangular_arbitrage strategy.**
  Shipped on branch `cursor/tradebot-optimization-agent-8956` — pending merge.
- [x] **Improve `pre-flight reject` messages.** Shipped #040 — reason strings
  now show bps (e.g. `net -35bps (gross +40bps - fees 40bps - slippage 5bps)`).
- [x] **Document the full Discord command set in `README.md`.** Shipped #043 —
  "Discord commands" section added with quick-reference table.

## Later (when there's slack)

- [ ] **Add a "what changed since last run?" summary command.** When the
  user is back at the keyboard, `TradeBot -recap` could show: PRs merged,
  config changes, notable trades, errors encountered. Saves time vs
  reading the chat log.
- [ ] **Wire a simple structured log sink.** Most logs are free-text;
  trades and pre-flight rejects could be ALSO emitted as JSONL so
  external analysis is easier.
- [ ] **Property-based tests for the fee calculation paths.** Use
  `hypothesis` to fuzz `compounded_taker_cost` etc., catch edge cases
  in multi-hop compounding.

---

## Done

(Add entries here as they ship — most recent first.)

- [x] **Document Discord commands in README.md.** #043 (2026-06-06)
- [x] **Surface ETH/BTC news context in auditor report.** #042 (2026-06-06)
- [x] **Stale-state-on-disk audit + regression tests.** #041 (2026-06-06)
  `RiskState.from_dict()` clears expired `paused_until`; watchdog 24h-cutoff
  test; PinTracker load test.
- [x] **bps in pre-flight reject messages.** #040 (2026-06-06)
- [x] **Centralise Discord webhook to `bot/notifications/discord_webhook.py`.** #039 (2026-06-06)
- [x] **pytest-cov in CI + `--cov-fail-under=53`.** #038 (2026-06-06)
- [x] **Add a `pytest --cov` run to CI + warn on silent state recovery.**
  Shipped by the 2026-05-30 auto run (commit `469534e`). _Note: landed on an
  `auto/…` branch; confirm it's merged to `main` before relying on it._
- [x] **Audit log levels across `bot/` + add `docs/logging_conventions.md`.**
  Shipped 2026-05-30 (commit `4e75761`, fee_engine WARNING→INFO). _Pending
  merge to `main`._
- [x] **Add `.gitattributes` to normalise line endings.** Shipped 2026-05-30
  (commit `ae6c8fa`, `* text=auto eol=lf`). _Pending merge to `main`._
