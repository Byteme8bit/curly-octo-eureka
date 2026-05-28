# 004 — Add MIN_ETH_RESERVE and MAX_ALT_ALLOCATION_PCT to .env

**Requested:** 2026-05-25
**Status:** complete

## Request
> yes add MIN_ETH_RESERVER and MAX_ALT_ALLOCATION_PCT to .env where appropirate. Thank you.

## Actions taken
- Added under `CORE_ASSETS=ETH,ADA,BTC` in `.env`:
  ```env
  # Portfolio allocation rules
  MIN_ETH_RESERVE=0.25
  MAX_ALT_ALLOCATION_PCT=0.40
  ```

## Notes
- Placement chosen near `CORE_ASSETS` since these define portfolio composition.
- Corrected typo in request (`MIN_ETH_RESERVER` → `MIN_ETH_RESERVE`).
