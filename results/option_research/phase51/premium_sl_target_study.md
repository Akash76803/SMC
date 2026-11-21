# Empirical Study: Index Structural SL vs Option Premium Stop Loss

## 1. Core Problem Formulation
In SMC index trading, the Stop-Loss is defined structurally by an invalidation level (e.g. Order Block high/low, Swing pivot). When buying options (CE/PE), traders often ask: *Should we exit when the index hits the structural SL, or should we set a hard premium stop-loss (e.g. -30% or delta-scaled)?*

## 2. Quantitative Comparison
| Exit Policy | Mechanism | Pros | Cons |
| :--- | :--- | :--- | :--- |
| **Policy 1: Index Structural Exit** | Exit option at market when index crosses invalidation price | Preserves SMC trade rationale; avoids false exits on option volatility spikes | Subject to theta decay during consolidation |
| **Policy 2: Fixed Delta Stop** | $\Delta \times \text{Index Risk}$ converted to absolute option points | Caps maximum financial loss per lot | Premature stop-outs during IV dips before index structure is invalidated |
| **Policy 3: Percentage Premium SL** | Exit at -25% or -30% of entry premium | Universal risk cap | Disconnects completely from market structure |

## 3. Recommendation
**Retain Policy 1 (Index Structural Exit) as Primary, backed by a catastrophic Policy 2 cap.** Options must be closed immediately when the underlying index structure breaks, without hoping for premium recovery.
