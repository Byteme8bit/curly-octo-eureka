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

- [ ] **Detect other "stale-state-on-disk" patterns.** We fixed
  `.auditor_state.json` (PR #8/#9). Audit the other persistent state
  files (`.paper_state.json`, `.watchdog_state.json`, `.discord_pins.json`)
  for similar TTL-based fields that `load()` doesn't prune. Add a regression
  test per file that loads a stale fixture and asserts the expired entries
  are dropped.
- [ ] **Surface the news review in the auditor report.** `scripts/review_news.py`
  now exists (read-only `NewsClient` wrapper). Wire the same headline summary
  into `bot/auditor/report.py` so the periodic audit cites 1–2 ETH/BTC
  headlines next to the regime read. Observability only — no decision changes.
- [ ] **Pin a minimum coverage threshold now that `pytest --cov` runs in CI.**
  CI emits coverage but doesn't fail on regressions. Add `--cov-fail-under`
  (start at the current measured number, ratchet up). Read the latest CI run
  to find the baseline first.

## Soon (anytime)

- [x] **Centralise the Discord webhook posting logic.** Shipped 2026-06-05 (#037 run).
  `bot/notifications/discord_webhook.py` — `post_webhook()` shared helper;
  both scripts now delegate to it.
- [ ] **`bot/auditor_service.py` is 600+ lines.** Worth splitting the
  proposal-application path from the chat path. Only do this after
  test coverage exists for the parts you'd extract.
- [x] **Add observability counters for triangular_arbitrage strategy.**
  Shipped 2026-06-05 (#037 run). `_loop_profit_with_reason()` + DEBUG scan
  log with `loops_scanned` and `reject_counts` dict.
- [x] **Improve `pre-flight reject` messages.** Shipped 2026-06-05 (#037 run).
  `bot/preflight.py` now formats all values in bps (e.g. `+40bps`).
- [ ] **Document the full Discord command set in `README.md`.** We have
  `DISCORD_COMMANDS.txt` but it's not linked from the README.

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

- [x] **Triangular-arb observability counters.** Shipped 2026-06-05 (feature 037).
  DEBUG scan log per tick: `loops_scanned`, best loop path/net, reject_counts by reason.
- [x] **CI coverage threshold `--cov-fail-under=50`.** Shipped 2026-06-05 (feature 038).
  `pytest-cov>=5.0.0` in `requirements-dev.txt`; CI enforces 50% floor.
  Current coverage: 53.93%.
- [x] **Centralised Discord `post_webhook()` helper.** Shipped 2026-06-05 (feature 039).
  `bot/notifications/discord_webhook.py`; both scripts now one-liner.
- [x] **Pre-flight reject messages in bps.** Shipped 2026-06-05 (feature 040).
  `bot/preflight.py` shows e.g. `net +12bps (gross +40bps - fees 40bps - slippage 5bps)`.
- [x] **Add a `pytest --cov` run to CI + warn on silent state recovery.**
  Shipped by the 2026-05-30 auto run (commit `469534e`). _Note: landed on an
  `auto/…` branch; confirm it's merged to `main` before relying on it._
- [x] **Audit log levels across `bot/` + add `docs/logging_conventions.md`.**
  Shipped 2026-05-30 (commit `4e75761`, fee_engine WARNING→INFO). _Pending
  merge to `main`._
- [x] **Add `.gitattributes` to normalise line endings.** Shipped 2026-05-30
  (commit `ae6c8fa`, `* text=auto eol=lf`). _Pending merge to `main`._
