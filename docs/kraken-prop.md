# Kraken Trade Prop — not supported by TradeBot (yet)

Kraken **Trade Prop** is a separate product inside Kraken Pro: you buy an
evaluation (e.g. Advanced Eval 1, $5k equity, profit target ~$5,450, max
drawdown ~$4,850), trade in a **simulated prop account**, and if you pass,
Kraken may fund a prop wallet where you keep a share of profits.

## What TradeBot uses today

TradeBot's live mode (`LIVE_ENABLED=1`) connects to your **personal Kraken spot
wallet** via the standard spot REST API (`ccxt.kraken` + `fetch_balance` /
market orders). It reads and writes `.live_state.json` for that spot account
only.

It does **not** read prop evaluation equity, prop profit targets, or prop
drawdown limits.

## Why prop is not wired in

| Topic | Spot wallet (supported) | Trade Prop eval (unsupported) |
|-------|-------------------------|-------------------------------|
| Product | Kraken spot | Kraken Pro → Prop trading mode |
| Account | Main / sub spot wallet | Separate evaluation account in account switcher |
| API | Standard Kraken spot API keys | Separate keys per prop account (same REST shape, different account context) |
| ccxt | `ccxt.kraken` | No dedicated Trade Prop class; would need prop-specific keys + guardrails |
| Bot goals | `GOAL_MILESTONES_USD` on live spot portfolio when armed | Prop $5k eval is a **different** capital pool — not mixed into bot milestones |

Kraken documents prop as an isolated account you switch to in Kraken Pro.
Evaluation rules (MDL, MDD, profit target) are enforced by Kraken's prop
product, not by this bot.

## Future work (stub only)

`.env` may define `PROP_ENABLED=1` as a **placeholder**. It has **no effect**
today. A future implementation would need at minimum:

1. Dedicated API keys for the prop evaluation account (not spot keys).
2. Prop-specific risk caps mapped to Kraken's MDL/MDD/profit-target rules.
3. Clear separation in reports: spot PnL vs prop PnL vs paper simulation.
4. Explicit user opt-in — prop eval failure has real cost.

Do not set `PROP_ENABLED=1` expecting prop trading until a feature log ships
implementation.

## Related docs

- [live-trading.md](live-trading.md) — arming real spot trading on Kraken
- [Kraken Prop FAQ](https://support.kraken.com/articles/kraken-prop-faq)
