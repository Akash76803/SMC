# Paper Fill Quality Report — Phase 5.1.2

Generated: 2026-11-21T17:50:48.213920+05:30

> [!IMPORTANT]
> These are INDICATIVE PAPER FILLS only. No actual orders were placed.
> Fill prices are simulation estimates using best-bid/ask + conservative slippage.
> Do NOT interpret as verified P&L or profitability evidence.

## Fill Quality Gates Applied

| Gate | Threshold | Action on Failure |
|------|-----------|-------------------|
| Stale quote | > 60.0s old at signal | STALE_QUOTE_REJECTED |
| Min quantity | ≥ 1 lot on each side | THIN_MARKET_FILL_UNCERTAIN |
| Max spread | ≤ 3% of ask | SPREAD_TOO_WIDE_FILL_UNCERTAIN |
| Session window | 09:16–15:15 IST | ENTRY_NOT_ALLOWED_<zone> |

## Fill Assessments

### SENSEX — 2026-11-17T14:52 — PE 81000.0

| Field | Value |
|-------|-------|
| Trading Symbol | `SENSEX2126181000PE` |
| Sim Exec At | 2026-11-17T14:53 |
| Bid / Ask | 110.0 / 112.5 |
| Bid Qty / Ask Qty | 20 / 20 |
| Spread % | 2.22% |
| Staleness at Signal | 5.0s |
| **Fill Quality** | **INDICATIVE_PAPER_FILL** |
| Entry Fill (buy) | 113.0 (ask + 0.5 slippage) |
| Exit Fill (sell) | 109.5 (bid − 0.5 slippage) |
| Notes | All quality gates passed — paper fill is INDICATIVE only |

### SENSEX — 2026-11-20T15:27 — CE 82000.0

| Field | Value |
|-------|-------|
| Trading Symbol | `SENSEX2126182000CE` |
| Sim Exec At | 2026-11-20T15:28 |
| Bid / Ask | 55.0 / 58.0 |
| Bid Qty / Ask Qty | 20 / 20 |
| Spread % | 5.17% |
| Staleness at Signal | 8.0s |
| **Fill Quality** | **SPREAD_TOO_WIDE_FILL_UNCERTAIN** |
| Entry Fill (buy) | 58.5 (ask + 0.5 slippage) |
| Exit Fill (sell) | 54.5 (bid − 0.5 slippage) |
| Notes | spread=5.17% exceeds 3% gate |

## NIFTY Signals (Live 4 days)

All 41 NIFTY signal candidates were rejected by SMC risk rules:
- 22 × `TARGET_INFEASIBLE_INDEX_TARGET_TOO_SMALL` (target < 50 pts or R:R < 1:2)
- 19 × `NO_VALID_OPPOSING_LIQUIDITY_TARGET`
- 0 confirmed trades — SMC risk rules are not weakened

No paper fills assessed for NIFTY (no signals passed SMC gating).

## Conclusion

SENSEX signal at 14:52 (17-Nov) qualifies as INDICATIVE_PAPER_FILL in research window.
SENSEX signal at 15:27 (20-Nov) is excluded from entry — session window violation.

Both fills carry INDICATIVE status only — not verified profitability.
