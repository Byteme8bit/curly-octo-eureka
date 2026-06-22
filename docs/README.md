# TradeBot documentation

Living architecture and engineering guide for the Kraken paper trading bot.

## Sections

| Section | Contents |
|---------|----------|
| [`architecture/`](architecture/) | System design, module responsibilities, tick lifecycle |
| [`conventions/`](conventions/) | Naming, code patterns, verification protocol |
| [`design/`](design/) | Style tokens (terminal + Discord), pattern library |

## Quick links

- **High-level overview:** [`architecture/overview.md`](architecture/overview.md)
- **Module map:** [`architecture/modules.md`](architecture/modules.md)
- **What happens on a tick:** [`architecture/tick-lifecycle.md`](architecture/tick-lifecycle.md)
- **Naming rules:** [`conventions/naming.md`](conventions/naming.md)
- **Code patterns:** [`conventions/patterns.md`](conventions/patterns.md)
- **How features are verified:** [`conventions/verification.md`](conventions/verification.md)
- **Color tokens:** [`design/color-tokens.md`](design/color-tokens.md)

## Operational docs

| Topic | Where |
|-------|-------|
| Live Kraken trading (arm, mirror, halts) | [`live-trading.md`](live-trading.md) |
| Phased rollout to live | [`path-to-live-trading.md`](path-to-live-trading.md) |
| Equity DCA + 50/50 portfolio buckets | [`dca-equities.md`](dca-equities.md) |
| Kraken xStocks / futures notes | [`kraken-equities-futures.md`](kraken-equities-futures.md) |
| Independent trade verifier | [`independent-verification.md`](independent-verification.md) |
| Project handoff (halt reset guide) | [`PROJECT_HANDOFF.md`](PROJECT_HANDOFF.md) |
| Windows auto-start (Task Scheduler) | [`auto-start-windows.md`](auto-start-windows.md) |
| Feature request history | [`../feature_logs/`](../feature_logs/) |
| Test suite | [`../tests/README.md`](../tests/README.md) |
| Run instructions | [`../README.md`](../README.md) |

## Maintaining these docs

When you add a module, change a public API, or introduce a pattern, update the relevant doc **in the same commit**. Drift is the enemy.
