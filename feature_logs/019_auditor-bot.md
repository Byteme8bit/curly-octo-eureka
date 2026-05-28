# 019 — Auditor bot (performance review + news context + tier-2 proposals)

**Requested:** 2026-05-27
**Status:** awaiting verification — pytest pending

## Request
> I want to audit this bot's portfolio performance and decisions. Maybe having another bot reviewing past transactions, market movement, news, and any other relevant resources that can help bring as much context awareness to improve the overall strategy. Then give a report and possibly forecast where PnL might head based on what it sees.

## Confirmed design answers
- **Cadence:** on-demand Discord command + scheduled daily + event-triggered (trade-count and PnL thresholds).
- **News:** free crypto news. Initially designed around CryptoPanic; revised on 2026-05-27 after the user flagged their pricing as too expensive — now defaults to a multi-feed RSS aggregator (CoinDesk, Cointelegraph, Decrypt, The Block, Bitcoin Magazine) with CoinGecko as opt-in JSON fallback. No API key required. Headlines only; no LLM summarization.
- **Scope:** read-only + propose + apply on `Auditor -confirm <id>` reply. Tier-2 governance only; no code edits.
- **Output:** Discord summary + full markdown file at `reports/YYYY-MM-DD/audit-HHMMSS.md`.
- **Forecast horizon:** auditor picks horizons based on data volume; prints confidence bands and never claims predictive certainty.

## Architecture summary
- `bot/auditor/` is a self-contained package: `analyzer` (pure functions over the broker's trade history), `forecaster` (stdlib-only PnL bands), `news_client` (urllib + retry/cache + CryptoPanic → CoinGecko fallback), `proposer` (heuristic tier-2 suggestions), `runtime_overrides` (JSON read/write), `state` (pending proposals + last-run markers), `report` (markdown + Discord summary renderers), `config` (`AuditorConfig` dataclass).
- `bot/auditor_service.py` runs a daemon scheduler thread (5-minute heartbeat). Exposes `run_audit`, `confirm_proposal`, `list_pending`, `revert`, `status`, `note_trade`. Daemon is started/stopped with the trading engine (mirrors `WatchdogService`).
- `bot/engine.py` instantiates the service, dispatches the new commands, calls `auditor.note_trade(trade)` after each successful trade, and starts/stops the auditor alongside the watchdog.
- `bot/discord_bot.py` adds `AUDITOR_ACTIONS`, expands `_PREFIXED_PATTERN` to accept `auditor|audit|au` plus trailing args for arg-bearing actions, ships `AuditorHelpText`, and folds the auditor block into the global `HelpText`.
- `config.py` adds `AUDITOR_*` settings + `_apply_runtime_overrides()`. Confirmed proposals only ever land in `runtime_overrides.json`; `.env` is never touched. Active overrides are logged at WARNING level on every startup so the running config is never surprising.

## Files added
- `bot/auditor/__init__.py` — package init; exports `AuditorConfig`, `AuditReport`, lazy `AuditorService`.
- `bot/auditor/config.py` — `AuditorConfig` dataclass.
- `bot/auditor/analyzer.py` — `analyze_trades()`, `PortfolioInsights`, `StrategyPerformance`.
- `bot/auditor/forecaster.py` — `forecast_pnl()`, `ForecastBand`, insufficient/trade-rate/bootstrap modes.
- `bot/auditor/news_client.py` — `NewsClient` (CryptoPanic + CoinGecko fallback), `NewsHeadline`.
- `bot/auditor/proposer.py` — `propose_changes()`, `ConfigProposal`, `ALLOWED_KNOBS`.
- `bot/auditor/runtime_overrides.py` — `apply_proposal()`, `list_overrides()`, `revert_override()`.
- `bot/auditor/state.py` — `AuditorState` (pending proposals + last-run markers).
- `bot/auditor/report.py` — `render_markdown_report()`, `render_discord_summary()`, `AuditReport`.
- `bot/auditor_service.py` — `AuditorService` daemon + `AuditorHelpText`.
- `tests/test_auditor.py` — ~25 unit tests (analyzer, forecaster, news client, proposer, runtime_overrides, state, report, service, config overrides, parser).
- `feature_logs/019_auditor-bot.md` — this file.

## Files modified
- `bot/engine.py` — imports + auditor instantiation + start/stop wiring + command dispatch + `note_trade` callback.
- `bot/discord_bot.py` — `AUDITOR_ACTIONS`, `_AUDITOR_ACTIONS_WITH_ARGS`, expanded `_PREFIXED_PATTERN`, refactored `_match_prefixed`, `AuditorHelpText`, global `HelpText` block.
- `config.py` — `AUDITOR_*` fields on `Settings`, `RUNTIME_OVERRIDE_KNOBS`, `_apply_runtime_overrides()` overlay, `load_settings()` builds a dict before constructing `Settings` so overrides win.
- `.env.example` — Auditor section with all `AUDITOR_*` defaults.
- `.gitignore` — `reports/`, `.auditor_state.json`, `runtime_overrides.json`.
- `docs/architecture/modules.md` — Auditor entries.
- `docs/architecture/overview.md` — Auditor in the high-level diagram + thread table.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_auditor.py -v
```

Live smoke (Discord owner):

```text
Auditor -summary       # quick recap
Auditor -review        # full audit; writes reports/YYYY-MM-DD/audit-HHMMSS.md
Auditor -forecast      # same audit, summary emphasizes forecast bands
Auditor -pending       # see active proposals + overrides
Auditor -confirm <id>  # apply a proposal (writes runtime_overrides.json)
Auditor -revert MIN_TRADE_EDGE
Auditor -status        # daemon status + next-run info
Auditor -help          # in-channel help text
```

Expected: Discord posts a concise auditor summary; a new file appears under `reports/`. On confirm, `runtime_overrides.json` shows up at the project root with the new knob; warning line on next start logs the active overrides. The daemon also fires the audit automatically once trade count crosses the trigger or a single trade's PnL is ≥ `AUDITOR_PNL_PCT_TRIGGER` of portfolio.

## Notes / open questions for the user
- **Reports rotation** — nothing prunes `reports/` yet. After the first weeks of use you may want a janitor that compresses or deletes very old audits.
- **News providers (revised 2026-05-27)** — CryptoPanic is too expensive on the paid plans, so the auditor now defaults to free RSS feeds. The chain is `AUDITOR_NEWS_PROVIDER=rss,coingecko`. The RSS aggregator pulls CoinDesk, Cointelegraph, Decrypt, The Block, and Bitcoin Magazine with no API key and no rate limits. CoinGecko stays as an opt-in JSON fallback. CryptoPanic remains supported for users with an existing key but is no longer the default. Override the RSS feed list via `AUDITOR_RSS_FEEDS=Name|URL,Name|URL,...`.
- **Forecast volume thresholds** — `<10`, `10-50`, `>50` were chosen as honest defaults; revisit once you have a few hundred real trades.
- **Tier-2 knobs** — `MIN_TRADE_EDGE`, `TRADE_SIZE_PCT`, `MIN_NET_PROFIT_PCT`, `IDLE_REEVAL_HOURS`, `STRATEGY_EXPLORATION_RATIO`. Policy knobs (ETH reserve, alt cap, fees, circuit breaker) are deliberately *not* proposable.
- **Restart required** — applying an override updates `runtime_overrides.json` but the engine reads it at process start, so a restart is needed for the new value to take effect.
