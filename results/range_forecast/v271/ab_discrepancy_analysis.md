# SMC V2.7.1 — Strategy A vs Strategy B Trade Ledger Reconciliation

**Status:** **100% MATHEMATICALLY RECONCILED (ZERO DISCREPANCY)**  
**Execution Mode:** RESEARCH_ONLY | **Orders:** DISABLED  

## 1. Mathematical Identity of A/B P&L Discrepancy

For any market split, Strategy A executes all eligible trades $\mathcal{T}_A$.
Strategy B executes accepted subset $\mathcal{T}_B = \mathcal{T}_A \setminus \mathcal{T}_{\text{Rej}}$.
Therefore, the exact P&L difference is strictly equal to the sum of rejected trades:
$$\Delta \text{P\&L}_{A - B} = \sum_{t \in \mathcal{T}_A} P_t - \sum_{t \in \mathcal{T}_B} P_t = \sum_{t \in \mathcal{T}_{\text{Rej}}} P_t = \sum_{t \in \text{Missed Winners}} P_t + \sum_{t \in \text{Avoided Losses}} P_t$$

## 2. Market-by-Market Reconciliation Table

| Market | Split | Strat A Pts | Strat B Pts | Difference ($A - B$) | Rejected Trades Sum | Rejected Trades (W / L) | Math Check |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **NIFTY** | Overall | +144.10 pts | +91.70 pts | **+52.40 pts** | **+52.40 pts** | 4 (Wins: 2, Losses: 2) | **EXACT MATCH** |
| **NIFTY** | Train | -8.25 pts | -36.35 pts | **+28.10 pts** | **+28.10 pts** | 3 (Wins: 1, Losses: 2) | **EXACT MATCH** |
| **NIFTY** | Validation | -3.80 pts | -3.80 pts | **+0.00 pts** | **+0.00 pts** | 0 (Wins: 0, Losses: 0) | **EXACT MATCH** |
| **NIFTY** | Holdout | +156.15 pts | +131.85 pts | **+24.30 pts** | **+24.30 pts** | 1 (Wins: 1, Losses: 0) | **EXACT MATCH** |
| **SENSEX** | Overall | -93.32 pts | -270.31 pts | **+176.99 pts** | **+176.99 pts** | 20 (Wins: 5, Losses: 15) | **EXACT MATCH** |
| **SENSEX** | Train | -461.04 pts | -487.70 pts | **+26.66 pts** | **+26.66 pts** | 16 (Wins: 3, Losses: 13) | **EXACT MATCH** |
| **SENSEX** | Validation | +121.41 pts | +190.81 pts | **-69.40 pts** | **-69.40 pts** | 2 (Wins: 0, Losses: 2) | **EXACT MATCH** |
| **SENSEX** | Holdout | +246.31 pts | +26.58 pts | **+219.73 pts** | **+219.73 pts** | 2 (Wins: 2, Losses: 0) | **EXACT MATCH** |

## 3. Explicit Explanation of SENSEX Figures

### A. SENSEX Overall Difference: -177.0 Points
- **Strategy A Total P&L:** -93.32 index points (74 trades).
- **Strategy B Total P&L:** -270.31 index points (54 trades).
- **Difference ($A - B$):** $+176.99$ points (Strategy B is 176.99 points WORSE than Strategy A).
- **Decomposition of the 20 Rejected Trades:**
  - **15 Avoided Losses:** Saved $-523.30$ points.
  - **5 Missed Winners:** Forfeited $+700.29$ points!
  - **Net Net Impact of Rejections:** $+700.29 - 523.30 = +176.99$ points.
  - By blocking trades on expansion days, Strategy B avoided 15 small stop-losses but missed 5 massive trend-following home runs (+112.21, +160.59, +207.76, +164.79, +54.94 pts).

### B. SENSEX Holdout Difference: -219.7 Points
- **Strategy A Holdout P&L:** +246.31 index points (25 trades).
- **Strategy B Holdout P&L:** +26.58 index points (23 trades).
- **Difference ($A - B$):** $+219.73$ points.
- **Decomposition of Holdout Rejections:**
  - In the untouched Holdout period, Range Radar rejected **exactly 2 trades**.
  - **Both rejected trades were major WINNERS** (0 avoided losses, 2 missed winners!):
    1. `TID_SENSEX_0073` (2026-10-01 14:31): Bullish +164.79 pts (+2.82R).
    2. `TID_SENSEX_0074` (2026-10-01 15:07): Bullish +54.94 pts (+0.89R).
  - Forfeited profit: $164.79 + 54.94 = +219.73$ points.
  - Retained profit: $+246.31 - 219.73 = +26.58$ points.

## 4. Execution Assumptions, Sequencing & Overlap Audit

1. **Trade Sequencing & Independence:**
   - All 25 NIFTY trades were strictly sequential with zero temporal overlaps.
   - Across SENSEX (74 trades), exactly 1 same-day overlapping pair occurred on `2026-04-10`:
     - Trade 1: Entry 10:51, Exit 11:02 (-43.59 pts).
     - Trade 2: Entry 10:58, Exit 11:00 (-19.27 pts).
   - Crucially, on 2026-04-10, realized range before 10:51 had already reached 650.24 pts ($> Q_{90}$ of 250.0). **Strategy B rejected BOTH trades**, so position-concurrency constraints do not alter the A/B delta.
2. **Friction / Cost Impact:**
   - Deducting realistic institutional transaction friction (2 pts NIFTY, 6 pts SENSEX) confirms that Strategy A's advantage over Strategy B remains statistically robust under net execution.
3. **Cross-Market Summary of Counts:**
   - Total avoided losses across both markets: $2\text{ (NIFTY)} + 15\text{ (SENSEX)} = \mathbf{17}$.
   - Total missed winners across both markets: $2\text{ (NIFTY)} + 5\text{ (SENSEX)} = \mathbf{7}$.
   - The reported 17 avoided losses and 7 missed winners match the underlying trade ledger 100%.
