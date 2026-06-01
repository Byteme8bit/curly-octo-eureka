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

_(cleared — see Done section)_

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

- [x] **Stale-state-on-disk TTL pruning** (feature 029). `WatchdogState.recent_errors`
  now stamped with `_ts` and pruned on load (24 h TTL). `RiskState.from_dict()`
  clears expired `paused_until` and resets stale `hour_window_start`/`trades_this_hour`.
  14 regression tests added. Shipped 2026-06-01.
- [x] **ETH/BTC market context in Forecast section** (feature 030). `render_markdown_report()`
  now injects a `**Market context:**` callout (1-2 ETH/BTC headlines) into the
  `## Forecast` section. Observability only. 3 new tests. Shipped 2026-06-01.
- [x] **CI coverage threshold** (feature 031). Added `pytest-cov>=5.0.0` to dev deps;
  CI now runs `--cov-fail-under=45` (baseline 47.14%, 288 tests). Shipped 2026-06-01.

- [x] **Add a `pytest --cov` run to CI + warn on silent state recovery.**
  Shipped by the 2026-05-30 auto run (commit `469534e`). _Note: landed on an
  `auto/…` branch; confirm it's merged to `main` before relying on it._
- [x] **Audit log levels across `bot/` + add `docs/logging_conventions.md`.**
  Shipped 2026-05-30 (commit `4e75761`, fee_engine WARNING→INFO). _Pending
  merge to `main`._
- [x] **Add `.gitattributes` to normalise line endings.** Shipped 2026-05-30
  (commit `ae6c8fa`, `* text=auto eol=lf`). _Pending merge to `main`._
