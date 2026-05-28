# 003 — Add strategy governance config to .env

**Requested:** 2026-05-25
**Status:** complete

## Request
> can you please add that New Config code block to the .env file for me? Append to bottom unless you think it is appropriate to place elsewhere in the .env

## Actions taken
- Appended to bottom of `.env` under section header `# Strategy governance — stick with winners, explore when flat`:
  - `IDLE_REEVAL_HOURS=2`
  - `IDLE_REEVAL_MAX_ATTEMPTS=3`
  - `STRATEGY_GROWTH_WINDOW_HOURS=4`
  - `STRATEGY_MIN_GROWTH_PCT=0.005`
  - `STRATEGY_STRONG_GROWTH_PCT=0.015`
  - `STRATEGY_SWITCH_EDGE_MARGIN=0.002`
  - `STRATEGY_EXPLORATION_RATIO=0.25`

## Notes
- Placement chosen to be after watchdog settings since strategy governance is functionally grouped with execution/runtime behavior.
- `IDLE_REEVAL_MAX_ATTEMPTS` included because it pairs with `IDLE_REEVAL_HOURS`.
