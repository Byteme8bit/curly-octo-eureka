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

_(cleared — see Done section below)_

## Soon (anytime)

- [ ] **Centralise the Discord webhook posting logic.** Both
  `scripts/monitor_kraken_changes.py` and `scripts/post_discord_alert.py`
  reimplement the same urllib JSON-POST. Extract to
  `bot/notifications/discord_webhook.py`, give both scripts a one-liner.
- [ ] **`bot/auditor_service.py` is 600+ lines.** Worth splitting the
  proposal-application path from the chat path. Only do this after
  test coverage exists for the parts you'd extract.
- [ ] **Add observability counters for triangular_arbitrage strategy.**
  How many loops scanned per tick? How many rejected for which reason?
  (Pure observability; do NOT change the strategy's decision logic.)
- [ ] **Improve `pre-flight reject` messages.** Currently shows raw
  decimals (`gross +0.0012 - fees 0.0040 - slippage 0.0005`). Could
  show basis points (12bps - 40bps - 5bps) which is easier to read.
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

(Most recent first.)

- [x] **Stale-state TTL pruning** (029) — `WatchdogState.recent_errors` now gets
  a `_ts` stamp and is pruned on load (7d); `RiskState.from_dict()` prunes expired
  `paused_until` and stale `hour_window_start`/`trades_this_hour`; 11 new tests.
  Shipped 2026-06-01.
- [x] **ETH/BTC market context in Forecast section** (030) — `render_markdown_report()`
  now includes a `_Market context (ETH/BTC):_` callout from the audit headlines;
  3 new tests. Shipped 2026-06-01.
- [x] **Pin CI coverage threshold** (031) — `pytest-cov>=5.0.0` added to dev deps;
  CI fails if coverage drops below 55% (baseline 58.07%). Shipped 2026-06-01.

- [x] **Add a `pytest --cov` run to CI + warn on silent state recovery.**
  Shipped by the 2026-05-30 auto run (commit `469534e`). _Note: landed on an
  `auto/…` branch; confirm it's merged to `main` before relying on it._
- [x] **Audit log levels across `bot/` + add `docs/logging_conventions.md`.**
  Shipped 2026-05-30 (commit `4e75761`, fee_engine WARNING→INFO). _Pending
  merge to `main`._
- [x] **Add `.gitattributes` to normalise line endings.** Shipped 2026-05-30
  (commit `ae6c8fa`, `* text=auto eol=lf`). _Pending merge to `main`._
