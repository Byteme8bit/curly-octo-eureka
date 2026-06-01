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

_(All items shipped — see Done.)_

## Soon (anytime)

- [ ] **`bot/auditor_service.py` is 600+ lines.** Worth splitting the
  proposal-application path from the chat path. Only do this after
  test coverage exists for the parts you'd extract.
- [ ] **Add observability counters for triangular_arbitrage strategy.**
  How many loops scanned per tick? How many rejected for which reason?
  (Pure observability; do NOT change the strategy's decision logic.)

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

- [x] **Stale TTL state pruning on load** (031): `PaperBroker._prune_stale_risk_fields`
  clears expired `paused_until` and resets the hour-window counter;
  `WatchdogState.seen_diagnostics` capped at 500 on load and at runtime.
  12 regression tests added. _(2026-06-01, branch `cursor/tradebot-optimization-agent-c685`)_
- [x] **CI coverage threshold at 50%** (032): `pytest-cov` added to
  `requirements-dev.txt`; CI now runs `--cov-fail-under=50`.
  _(2026-06-01, branch `cursor/tradebot-optimization-agent-c685`)_
- [x] **Centralise Discord webhook posting** (033): `bot/notifications/discord_webhook.py`
  extracts the shared urllib POST; both `scripts/post_discord_alert.py` and
  `scripts/monitor_kraken_changes.py` use it.
  _(2026-06-01, branch `cursor/tradebot-optimization-agent-c685`)_
- [x] **Pre-flight reject messages in basis points** (034): `bot/preflight.py`
  reason strings now show `40bps` instead of `0.0040`.
  _(2026-06-01, branch `cursor/tradebot-optimization-agent-c685`)_
- [x] **Document Discord command set in README** (035): "Discord commands"
  section with quick-reference table added; links to `DISCORD_COMMANDS.txt`.
  _(2026-06-01, branch `cursor/tradebot-optimization-agent-c685`)_

- [x] **Add a `pytest --cov` run to CI + warn on silent state recovery.**
  Shipped by the 2026-05-30 auto run (commit `469534e`). _Note: landed on an
  `auto/…` branch; confirm it's merged to `main` before relying on it._
- [x] **Audit log levels across `bot/` + add `docs/logging_conventions.md`.**
  Shipped 2026-05-30 (commit `4e75761`, fee_engine WARNING→INFO). _Pending
  merge to `main`._
- [x] **Add `.gitattributes` to normalise line endings.** Shipped 2026-05-30
  (commit `ae6c8fa`, `* text=auto eol=lf`). _Pending merge to `main`._
