# SMC Signal Rejection Analysis: 41 NIFTY Candidates

## 1. Breakdown of Rejections (17–20 Nov 2026)

During the 4 live observation sessions, exactly 41 continuation observations were detected in NIFTY 50. All 41 were rejected by existing institutional SMC risk gates:

| Rejection Reason | Count | Percentage | Risk Management Function |
| :--- | :---: | :---: | :--- |
| `TARGET_INFEASIBLE_INDEX_TARGET_TOO_SMALL` | **22** | **53.7%** | Enforces minimum 50.0 index points reward & 1:2 R:R. Prevents low-expectancy scalps |
| `NO_VALID_OPPOSING_LIQUIDITY_TARGET` | **19** | **46.3%** | Ensures a clear opposing liquidity pool exists to draw price. Prevents entering into consolidation voids |

## 2. Quantitative Conclusion
**Do NOT weaken SMC risk rules.** Relaxing the 50-point target or opposing liquidity requirement would artificially increase trade count while dramatically degrading expectancy due to option bid/ask friction and theta decay.
