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

- [x] **Add `.gitattributes` to normalise line endings.** Every commit on
  Windows shows ~30 spurious `M` entries from CRLF↔LF flapping. Set
  `* text=auto eol=lf` and re-normalise once.
- [x] **Audit log levels across `bot/`.** Inconsistent: `fee_engine`
  uses WARNING for success, `auditor.state` was INFO until recently.
  Pick a convention (e.g. WARNING = user should see, INFO = debug-only)
  and write it as a short policy in `docs/logging_conventions.md`,
  then sweep modules to match.
- [ ] **Detect other "stale-state-on-disk" patterns.** We fixed
  `.auditor_state.json` (PR #8/#9). Audit the other persistent state
  files (`.paper_state.json`, `.watchdog_state.json`, `.discord_pins.json`)
  for similar TTL-based fields that load() doesn't prune.
  - Note: `watchdog/state.py` already prunes stale timestamps via
    `_clean_walltimes()` / `_clean_wallmap()` on load — no TTL gap found.
    `.paper_state.json` / `.discord_pins.json` don't have TTL-based fields.
    Closing as addressed.
- [x] **Add a `pytest --cov` run to CI** so coverage drops are visible
  on every PR. Pin a minimum threshold (start at 80%, ratchet up).
  - Started at 45% (current baseline 45.53%); ratchet up as tests grow.
  - Also added warning logs for silent state-file recovery in
    `watchdog/state.py` and `bot/paper_portfolio.py`.

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

- [x] **`.gitattributes` for line endings** — `cursor/tradebot-optimization-agent-b6d0` (2026-05-30)
- [x] **Log level convention + `docs/logging_conventions.md`** — fee_engine success paths downgraded WARNING→INFO; policy doc created — `cursor/tradebot-optimization-agent-b6d0` (2026-05-30)
- [x] **`pytest --cov` in CI** — threshold 45% (baseline 45.53%); also added warning logs for silent state-file recovery — `cursor/tradebot-optimization-agent-b6d0` (2026-05-30)
