# 099 — Visible ETH session/last-fill deltas

**Requested:** 2026-08-07 04:05 PDT
**Status:** complete

## Request
User still believes holdings are not changing while trade count rises.

## Explanation
Triangular fills only add ~**0.00009 ETH** (~$0.17) each. Total ETH did rise (0.520 → ~0.574) but per-refresh changes look like noise.

## Actions taken
- Metric **ETH Δ sess** vs `paper_baseline.json`
- Holdings footer: session Δ + last fill Δ
- ETH qty always 6 decimal places
- Portfolio history appends live `paper_portfolio.json` point (chart was stuck ~$1410)
- `app.js?v=052`, deploy + restart dashboard
