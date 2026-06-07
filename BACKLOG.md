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

- [ ] **Surface the news review in the auditor report.** `scripts/review_news.py`
  now exists (read-only `NewsClient` wrapper). Wire the same headline summary
  into `bot/auditor/report.py` so the periodic audit cites 1–2 ETH/BTC
  headlines next to the regime read. Observability only — no decision changes.

## Soon (anytime)

- [ ] **Centralise the Discord webhook posting logic.** Both
  `scripts/monitor_kraken_changes.py` and `scripts/post_discord_alert.py`
  reimplement the same urllib JSON-POST. Extract to
  `bot/notifications/discord_webhook.py`, give both scripts a one-liner.
- [ ] **`bot/auditor_service.py` is 600+ lines.** Worth splitting the
  proposal-application path from the chat path. Only do this after
  test coverage exists for the parts you'd extract.
- [ ] **Improve `pre-flight reject` messages.** Currently shows raw
  decimals (`gross +0.0012 - fees 0.0040 - slippage 0.0005`). Could
  show basis points (12bps - 40bps - 5bps) which is easier to read.
- [ ] **Document the full Discord command set in `README.md`.** We have
  `DISCORD_COMMANDS.txt` but it's not linked from the README.
- [ ] **Wire preflight_reject into StructuredLogger.** `bot/structured_log.py`
  exposes `log_preflight_reject()` but it's not called yet. Wire it in
  `bot/engine.py` at the two points where `pf.allowed` is False.

## Later (when there's slack)

- [ ] **Add a "what changed since last run?" summary command.** When the
  user is back at the keyboard, `TradeBot -recap` could show: PRs merged,
  config changes, notable trades, errors encountered. Saves time vs
  reading the chat log.
- [ ] **Property-based tests for the fee calculation paths.** Use
  `hypothesis` to fuzz `compounded_taker_cost` etc., catch edge cases
  in multi-hop compounding.
- [ ] **Ratchet coverage threshold to 56%.** Currently at 55.53%.
  Add ~5-10 more tests (good targets: `bot/risk.py` at 21%, `bot/markets.py`
  at 37%, `bot/pin_tracker.py` at 50%) to push over 56%, then bump
  `--cov-fail-under` in test.yml.

---

## Done

(Add entries here as they ship — most recent first.)

- [x] **Detect stale `paused_until` in `.paper_state.json`.**
  `RiskState.from_dict()` now prunes expired timestamps on load so a crashed
  bot doesn't wake up still paused. Feature 038, branch
  `cursor/tradebot-optimization-agent-4058`.
- [x] **Pin coverage threshold.** Added `pytest-cov>=5.0.0` to dev deps;
  CI fails at `--cov-fail-under=54` (baseline 55.53%). Feature 039.
- [x] **Observability counters for triangular_arbitrage.** Scan/no-market/
  below-min counts logged at DEBUG each tick. Feature 040.
- [x] **JSONL structured log sink.** `bot/structured_log.py` + wired into
  `BotFileLogger.log_tick()` for filled trades. Feature 041.

- [x] **Add a `pytest --cov` run to CI + warn on silent state recovery.**
  Shipped by the 2026-05-30 auto run (commit `469534e`). _Note: landed on an
  `auto/…` branch; confirm it's merged to `main` before relying on it._
- [x] **Audit log levels across `bot/` + add `docs/logging_conventions.md`.**
  Shipped 2026-05-30 (commit `4e75761`, fee_engine WARNING→INFO). _Pending
  merge to `main`._
- [x] **Add `.gitattributes` to normalise line endings.** Shipped 2026-05-30
  (commit `ae6c8fa`, `* text=auto eol=lf`). _Pending merge to `main`._
