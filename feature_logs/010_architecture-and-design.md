# 010 — Professional architecture, docs, tokens, and verification protocol

**Requested:** 2026-05-25 11:43 PDT
**Status:** awaiting verification — sandbox locked

## Request
> 1. Please ignore the discord chat log files for GitHub commits.
> 2. You should carefully test each change/feature request before moving onto the next request.
> 3. I want you to start a professional architecture and system design for this project implementing proper folder structures, color tokens, architecture docs, naming conventions, and pattern libraries.

## Actions taken

### 1. Gitignore for Discord chat logs (point 1)
- Broadened `.gitignore` from a single `logs/discord_chat.log` to:
  ```
  logs/discord_chat*.log
  logs/discord_chat.log.*
  ```
- Covers rotated/dated chat-log variants.

### 2. Verification protocol (point 2)
- New doc `docs/conventions/verification.md` — defines three tiers (automated test / smoke script / live observation) and the rule that a feature is **not done** until verification has actually run and passed.
- New doc `docs/conventions/contributing.md` — per-request workflow + code-review checklist that includes "tests added or updated" and "tests pass locally".
- Adopted "awaiting verification" status for feature logs when the sandboxed shell prevents running tests in-agent.

### 3. Architecture and design (point 3)

**New folder structure**
```
docs/
├── README.md
├── architecture/
│   ├── overview.md
│   ├── modules.md
│   └── tick-lifecycle.md
├── conventions/
│   ├── naming.md
│   ├── patterns.md
│   ├── verification.md
│   └── contributing.md
└── design/
    ├── color-tokens.md
    ├── discord-style-guide.md
    └── pattern-library.md

tests/
├── README.md
├── __init__.py
├── conftest.py
├── test_portfolio_constraints.py
├── test_strategy_governor.py
├── test_watchdog_state.py
├── test_kraken_retry.py
└── test_ui_tokens.py

bot/
└── ui_tokens.py          ← new: semantic terminal + Discord tokens
```

**Color tokens**
- New module `bot/ui_tokens.py` exposes:
  - `TerminalToken` — semantic ANSI roles (`SUCCESS`, `ERROR`, `BUY`, `SELL`, `MUTED`, etc.)
  - `DISCORD` (`DiscordEmbedColor`) — paired `0xRRGGBB` integers for embeds
  - `ASSET_PALETTE` + `asset_color()` for per-asset coloring
  - Helpers: `colorize(text, token)`, `pnl_color(value)`
- Refactored `bot/display.py` to use the new tokens (drops `ASSET_COLORS` literal, drops inline `Fore.GREEN if ... else Fore.RED` patterns).

**Architecture docs**
- `docs/architecture/overview.md` — process model, layered diagram, persistence, configuration story
- `docs/architecture/modules.md` — every module's role + public surface, tagged by layer (application / domain / infrastructure / presentation)
- `docs/architecture/tick-lifecycle.md` — what happens inside `TradingEngine.tick()`, timing budget, failure modes, shutdown sequence

**Conventions**
- `docs/conventions/naming.md` — file, class, function, env-var, boolean, and domain-term naming rules
- `docs/conventions/patterns.md` — the 10 reusable patterns (config, dataclass results, wall-clock vs. monotonic, retry+cache, cooperative shutdown, etc.)

**Pattern library**
- `docs/design/pattern-library.md` — copy-pasteable snippets for: frozen settings, retry with backoff, cooperative threads, persisted state, defensive intents, wall-clock decision tree, Discord post + chat mirror.

**Discord style guide**
- `docs/design/discord-style-guide.md` — message types, layout rules, embed color map, pinning rules, command list, what not to do.

### 4. Testing scaffold
- New `tests/` folder with pytest config (`pytest.ini`, `conftest.py`).
- Initial tests covering features 001 (constraints), 002 (governor), 006 (watchdog state), 008 (Kraken retry), and the new tokens module.
- `requirements-dev.txt` adds pytest pinned `>=8`.

## Files added
- `bot/ui_tokens.py`
- `docs/README.md`
- `docs/architecture/overview.md`
- `docs/architecture/modules.md`
- `docs/architecture/tick-lifecycle.md`
- `docs/conventions/naming.md`
- `docs/conventions/patterns.md`
- `docs/conventions/verification.md`
- `docs/conventions/contributing.md`
- `docs/design/color-tokens.md`
- `docs/design/discord-style-guide.md`
- `docs/design/pattern-library.md`
- `tests/README.md`
- `tests/test_portfolio_constraints.py`
- `tests/test_strategy_governor.py`
- `tests/test_watchdog_state.py`
- `tests/test_kraken_retry.py`
- `tests/test_ui_tokens.py`
- `requirements-dev.txt`

## Files modified
- `.gitignore` — broader Discord chat log glob
- `bot/display.py` — uses `ui_tokens` instead of raw colorama + inline literals

## Verification
The Cursor agent shell is currently sandbox-locked on Windows (see `feature_logs/007`), so pytest could not run in-agent. To verify locally:

```powershell
cd C:\Users\lynch\eth-trading-bot
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -v
```

Expected: all tests in `tests/` pass. Status of this feature will be flipped to `complete` once the suite runs green.

## Migration plan (incremental, no big bang)
Touch a module → migrate it. Future PRs should:
- Replace any remaining `Fore.RED/GREEN` literals in `bot/error_report.py`, `bot/report.py`, `bot/alerts.py` with `TerminalToken` equivalents
- Add Discord embeds (using `DISCORD.*`) when we move away from plain-text Discord posts
- Add module rows to `docs/architecture/modules.md` whenever a new file lands
