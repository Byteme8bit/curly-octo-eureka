# Color tokens

All colors live in `bot/ui_tokens.py`. Two parallel token sets:

1. **`TerminalToken`** — `colorama` ANSI strings for terminal output.
2. **`DISCORD` (`DiscordEmbedColor`)** — `0xRRGGBB` integers for Discord embeds.

Plus a separate `ASSET_PALETTE` for per-asset coloring (kept distinct so we can swap the semantic palette without disturbing asset colors).

## Why centralize

- Eliminate scattered `Fore.RED` / `0xE74C3C` literals.
- Single switch to rebrand the bot (e.g., dark theme, accessibility palette).
- Aligned terminal ↔ Discord colors so a "buy" looks the same green in both surfaces.

## Semantic vs. literal

Use the **semantic** token by intent:

```python
from bot.ui_tokens import TerminalToken, colorize

print(colorize("trade executed", TerminalToken.SUCCESS))
```

Not:

```python
from colorama import Fore  # ← avoid in new code
print(Fore.GREEN + "trade executed")
```

## Token catalog (semantic)

| Token | Terminal | Discord | Used for |
|-------|----------|---------|----------|
| `SUCCESS` | green | `0x2ECC71` | Trade executed, positive PnL, healthy watchdog |
| `ERROR` | red | `0xE74C3C` | Bot errors, alerts, paused, crashed checks |
| `WARNING` | yellow | `0xF1C40F` | Stale data, near-floor warnings, slow Kraken |
| `INFO` | cyan | `0x3498DB` | Status updates, considering lists |
| `MUTED` | bright-black | `0x95A5A6` | Captions, timestamps, "nothing queued" |
| `EMPHASIS` | white+bold | — | Section headers |
| `BUY` | green | `0x27AE60` | Buy-side trade events |
| `SELL` | red | `0xC0392B` | Sell-side trade events |
| `POSITIVE` / `NEGATIVE` / `NEUTRAL` | green / red / white | — | PnL signs |

## Token catalog (event-specific Discord)

| Token | Hex | Used for |
|-------|-----|----------|
| `TRADE_EXECUTED` | `0x9B59B6` (purple) | Trade alert pings |
| `HEARTBEAT` | `0x5865F2` (Discord blurple) | Watchdog heartbeats |
| `HIBERNATING` | `0xD35400` (burnt orange) | Auto drawdown pause |
| `CIRCUIT_BREAKER` | `0x8E44AD` (purple) | Hard halt, awaiting `resume-trading` |
| `ADAPTIVE_MODE` | `0x1ABC9C` (teal) | Idle relaxation engaged |
| `STRATEGY_SWITCH` | `0x16A085` (teal-dark) | Governor switched dominant strategy |
| `MILESTONE` | `0xFFD700` (gold) | Profit thresholds, anniversaries |

## Per-asset palette

`ASSET_PALETTE` maps known assets to colorama colors and falls back to `Fore.WHITE` for anything new. To add an asset, edit the dict in `ui_tokens.py` and pick a color **not already used in the semantic palette**.

## Helper functions

| Function | Purpose |
|----------|---------|
| `colorize(text, token)` | Wraps text in an ANSI sequence + auto-reset |
| `asset_color(asset)` | Returns the asset's ANSI color (case-insensitive, fallback-safe) |
| `pnl_color(value)` | `POSITIVE` if `value >= 0` else `NEGATIVE` |

## Migration plan (incremental)

Already migrated:

- [x] `bot/display.py` — uses `TerminalToken`, `asset_color`, `pnl_color`, `colorize`

Pending:

- [ ] `bot/report.py` — currently text-only; will adopt Discord embed colors when embeds are added.
- [ ] `bot/error_report.py` — same.
- [ ] `bot/alerts.py` — wrap any alert colors in `TerminalToken`.

When migrating, **never delete `colorama.Fore` imports until all uses inside that file are switched.** Mixed states are fine during a transition commit.

## Accessibility note

Colors are decoration only — never the sole channel for information. Every state has a textual label (e.g., "TRADE EXECUTED", "[ERROR]") so the bot remains usable for color-blind operators and in plain log captures.
