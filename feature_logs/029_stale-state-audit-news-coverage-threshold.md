# 029 — Stale-state audit, news in auditor report, coverage threshold

**Requested:** 2026-06-01 (auto-maintenance run)
**Status:** complete

## Request

Three BACKLOG items shipped in one maintenance cycle:

1. **Detect other "stale-state-on-disk" patterns** — audit `.paper_state.json`,
   `.watchdog_state.json`, `.discord_pins.json` for TTL-based fields that `load()`
   doesn't prune. Add regression tests per file.

2. **Surface the news review in the auditor report** — wire 1–2 ETH/BTC headline
   snippets into the "Headline numbers" section of `bot/auditor/report.py` so the
   regime read has immediate market context.

3. **Pin a minimum coverage threshold** — add `pytest-cov` to CI and gate it at
   the current measured baseline (45 %).

## Actions taken

### 1. `bot/paper_broker.py` — `RiskState._prune_stale()`

Added a new static method `_prune_stale()` called from `RiskState.from_dict()`.
It eagerly clears two categories of expired TTL state, logging a WARNING for
each so operators know a stale entry was dropped:

- **`paused_until`**: if the ISO timestamp is in the past (or unparseable), the
  field is set to `None` and `hibernate_alert_sent` is reset to `False`. This
  mirrors the auditor-state fix from PR #8 / feature 019: without this, a bot
  that restarts after a hibernation window expires still sees `paused_until` in
  memory until the first `update_portfolio()` call.

- **`hour_window_start` / `trades_this_hour`**: if the window is ≥ 3600 s old
  (or unparseable), `trades_this_hour` is reset to 0 and `hour_window_start` is
  cleared. Without this, a state file saved with `trades_this_hour=5` during the
  old hour would incorrectly count against the new session's hourly limit on
  restart.

**`WatchdogState`** (`watchdog/state.py`) already prunes `error_timestamps`,
`watchdog_error_timestamps`, `seen_error_keys`, and `error_pin_windows` via
`_clean_walltimes` / `_clean_wallmap` in `load()`. No code change needed.

**`PinTracker`** (`.discord_pins.json`) has no TTL-based fields — it stores
Discord message IDs. The existing channel-ID guard in `_load()` silently
discards data from a different channel. No code change needed.

### 2. `tests/test_paper_state_stale.py` (new file)

15 regression tests covering:
- Expired and future `paused_until` (4 tests)
- Expired, recent, boundary, and unparseable `hour_window_start` (5 tests)
- Existing `WatchdogState` load-time TTL pruning (4 regression guards)
- `PinTracker` channel-ID guard (2 tests)

### 3. `bot/auditor/report.py` — `render_markdown_report()`

After the "Headline numbers" section, filter `headlines` for entries that
mention ETH or BTC tickers and render up to 2 as "**Recent ETH/BTC news:**"
bullets. Purely observability — no decision logic changed.

### 4. `requirements-dev.txt` + `.github/workflows/test.yml`

- Added `pytest-cov>=5.0.0` to `requirements-dev.txt`.
- Updated CI `pytest` command to:
  `pytest --cov=bot --cov=watchdog --cov-report=term-missing --cov-fail-under=45`
  Baseline measured at 45 % on this branch. CI will now fail if coverage drops
  below that floor.

## Files changed

- **Modified** `bot/paper_broker.py` — `RiskState._prune_stale()` + `from_dict()` call
- **Modified** `bot/auditor/report.py` — ETH/BTC news snippet in "Headline numbers" section
- **Modified** `requirements-dev.txt` — added `pytest-cov>=5.0.0`
- **Modified** `.github/workflows/test.yml` — `--cov` + `--cov-fail-under=45`
- **New** `tests/test_paper_state_stale.py` — 15 regression tests
- **New** `feature_logs/029_stale-state-audit-news-coverage-threshold.md` — this file

## Verification

```bash
python3 -m pytest tests/test_paper_state_stale.py -v   # 15 passed
python3 -m pytest                                       # 289 passed (was 274)
```

## News context

BTC and ETH started June 2026 in the red (BTC ETF outflows at record levels;
ETH/BTC both showing downside on Jun 1). This confirms no strategy-logic changes
are warranted by news alone. The ETH/BTC news snippet added to the auditor
report will surface exactly this kind of context on each scheduled audit.
