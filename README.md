# ETH + ADA Paper Trading Bot (Kraken)

Paper-trades on Kraken using live market data. Supports **USD pairs** and **crypto-to-crypto** swaps (e.g. ETH -> ADA via ADA/ETH).

## Setup

```bash
cd eth-trading-bot
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

## Run

```bash
python main.py
```

## Logs and receipts

| Location | Contents |
|---|---|
| `logs/bot.log` | **Single append-only file** — every tick logs portfolio, full momentum ranks, holdings, blocked reasons, and trades |
| `receipts/` | **One JSON file per trade** — e.g. `20260525-045200-buy-ADA-ETH.json` |

The terminal shows a clean summary. Momentum ranks are **not** printed to the terminal but are written to `logs/bot.log` each cycle.

## Trading routes

- **USD pairs**: buy/sell with USD (ETH/USD, ADA/USD, ...)
- **Cross pairs**: auto-discovered from Kraken (~20 pairs among watched assets)
  - ETH -> ADA uses **BUY ADA/ETH** (spend ETH, receive ADA)
  - ADA -> ETH uses **SELL ADA/ETH** (spend ADA, receive ETH)
  - Similar routes for SOL/ETH, DOT/ETH, etc.

## GitHub backup

Remote: `https://github.com/Byteme8bit/curly-octo-eureka`

First-time setup (run from project root):

```powershell
python scripts/git_setup.py
```

That initializes git, stages all source files (never `.env`), commits, and pushes to `main`. If push fails, authenticate with `gh auth login` or your Git credential manager, then re-run the script.

**Never committed:** `.env`, logs, receipts, paper state, venv, runtime diagnostics.

## Key settings

| Setting | Default | Purpose |
|---|---|---|
| `MAX_TRADES_PER_HOUR` | 12 | Up to 12 trades per hour |
| `TRADE_COOLDOWN_SECONDS` | 180 | 3 min minimum between trades |
| `MIN_TRADE_EDGE` | 0.006 | Momentum must beat fees |
| `CORE_ASSETS` | ETH,ADA,BTC | Protected from rotation churn |

## Discord commands

Full command reference: [`DISCORD_COMMANDS.txt`](DISCORD_COMMANDS.txt)

Quick reference — prefix every command with `TradeBot` or `WatchDog`:

| Command | What it does |
|---|---|
| `TradeBot -status` | Current portfolio snapshot |
| `TradeBot -portfolio` | Detailed holdings + PnL |
| `TradeBot -trades` | Recent trade history |
| `TradeBot -reset` | Reset paper state and error counts |
| `TradeBot -resume-trading` | Exit hibernation / re-evaluation mode |
| `WatchDog -status` | Watchdog health score |
| `WatchDog -clearchat` | Prune pinned messages |
| `Auditor -report` | Trigger an on-demand audit |
| `Auditor -pending` | List pending config proposals |
| `Auditor -confirm <id>` | Apply a config proposal |

## Documentation

- **Architecture, modules, tick lifecycle:** [`docs/architecture/`](docs/architecture/)
- **Naming, code patterns, verification protocol:** [`docs/conventions/`](docs/conventions/)
- **Color tokens, Discord style, pattern library:** [`docs/design/`](docs/design/)
- **Feature history:** [`feature_logs/`](feature_logs/)
- **Tests:** [`tests/README.md`](tests/README.md)

## Running tests

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
```
