# MASTER CODEX EXECUTION SPECIFICATION
## Project: SMC & Multi-Strategy Indian Options Intraday Research Terminal
## Target Directory: `e:\Project\SMC`

---

## 1. OBJECTIVE & ARCHITECTURAL PRINCIPLES

Transform the current over-filtered monolithic SMC system into a **Decoupled, Autonomous Multi-Engine Architecture**.

### Key Rules:
1. **Zero Cross-Engine Blocking:**
   - No single engine waits for another engine.
   - If SMC Sweep triggers, it issues its trade signal immediately.
   - If Candlestick Hammer triggers, it issues its trade signal immediately.
   - If ORB triggers, it issues its trade signal immediately.
2. **Confluence as Bonus Badge, NOT a Gate:**
   - When 2 or more independent engines agree in direction, the Dispatcher adds a `confluence_score: HIGH` badge, but single-engine setups trigger with full trade cards without delay.
3. **Strict Research / Safety Mode:**
   - `orders_enabled: False`, `research_only: True`. Never alter broker credentials or place actual orders.
   - Risk:Reward minimum $\ge 1:2.0$.
   - Index SL and Target clearly defined alongside option strike recommendations.

---

## 2. REPOSITORY STRUCTURE & MODULE BREAKDOWN

```
e:\Project\SMC\
├── smc\
│   ├── smc_module_sweep.py       <-- [NEW] SMC Engine 1: Liquidity Sweep / Turtle Soup Reversal
│   ├── smc_module_mss.py         <-- [NEW] SMC Engine 2: Market Structure Shift & Displacement
│   ├── smc_module_fvg.py         <-- [NEW] SMC Engine 3: Fair Value Gap Imbalance Fill
│   ├── smc_module_ob.py          <-- [NEW] SMC Engine 4: Extreme Order Block Retest
│   ├── strategy_candlestick.py   <-- [ENHANCE] Engine 5: 23 Candlestick Patterns with Trend & Volume
│   ├── strategy_pdh_pdl.py       <-- [NEW] Engine 6: Groww Masterclass PDH/PDL Breakout & 50% Mid
│   ├── strategy_snr_vwap.py      <-- [EXISTING] Engine 7: SNR & VWAP Pullback Bounce
│   ├── strategy_orb.py           <-- [EXISTING] Engine 8: 9:15-9:30 Opening Range Breakout
│   ├── strategy_oi_trap.py       <-- [EXISTING] Engine 9: Option Chain OI Trap & Unwinding
│   ├── multi_strategy_terminal.py<-- [ENHANCE] Central Dispatcher & Parallel Aggregator
│   ├── app_terminal_v316.py      <-- [ENHANCE] Web UI supporting independent card rendering
│   └── option_strike_engine.py   <-- [EXISTING] ATM/ITM Strike Card Generator
└── tests\
    ├── test_smc_module_sweep.py  <-- Unit tests
    ├── test_smc_module_mss.py    <-- Unit tests
    ├── test_smc_module_fvg.py    <-- Unit tests
    ├── test_smc_module_ob.py     <-- Unit tests
    ├── test_strategy_candlestick.py
    ├── test_strategy_pdh_pdl.py
    └── test_multi_strategy_terminal.py
```

---

## 3. UNIFIED SIGNAL DATA SCHEMA (JSON CONTRACT)

Every strategy engine module must return a list of dictionaries with this exact schema:

```json
{
  "strategy": "SMC_SWEEP | SMC_MSS | SMC_FVG | SMC_OB | CANDLESTICK | PDH_PDL | SNR_VWAP | ORB | OI_TRAP",
  "setup_id": "UNIQUE_STRING_ID",
  "pattern_or_trigger": "HAMMER_SWEEP | MORNING_STAR | PDH_ACCEPTANCE | TURTLE_SOUP_PDL | ...",
  "timestamp": "2026-11-18T14:15:00+05:30",
  "symbol": "NIFTY | SENSEX",
  "direction": "BULLISH | BEARISH",
  "side": "CE | PE",
  "entry": 25210.0,
  "stop_loss": 25195.0,
  "target": 25240.0,
  "index_sl_pts": 15.0,
  "index_target_pts": 30.0,
  "risk_reward": 2.0,
  "timeframe": "1m | 5m | 15m",
  "confirmation_source": "ENGINE_NAME",
  "strikes": [
    {
      "strike": 25200,
      "option_type": "CE",
      "premium_entry": 115.5,
      "premium_sl": 105.0,
      "premium_target": 136.5
    }
  ],
  "research_only": true,
  "orders_enabled": false
}
```

---

## 4. DETAILED SPECIFICATION FOR EACH ENGINE

### 4.1 SMC Engine 1: Liquidity Sweep Reversal (`smc/smc_module_sweep.py`)
* **Trigger Condition:**
  - Price sweeps previous Swing Low or PDL with a low wick $\ge 50\%$ of candle range and closes back above the level.
  - Or sweeps previous Swing High or PDH with an upper wick $\ge 50\%$ and closes back below the level.
* **Action:**
  - Immediate trigger on candle close without waiting for deep mitigation or multiple steps.
  - Direction: Bullish (CE) on Low Sweep; Bearish (PE) on High Sweep.
  - SL: Wick extreme $\pm 2$ pts. Target: 1:2 R:R (Target 1) or opposite swing (Target 2).

### 4.2 SMC Engine 2: Market Structure Shift & Displacement (`smc/smc_module_mss.py`)
* **Trigger Condition:**
  - Decisive Break of Structure (BOS / MSS) where a 5m candle closes outside previous swing high/low with large body ($\ge 60\%$ of span) indicating displacement.
* **Action:**
  - Momentum trend continuation trigger in direction of break.
  - SL: Opposite end of displacement candle. Target: 1:2 R:R.

### 4.3 SMC Engine 3: Fair Value Gap (`smc/smc_module_fvg.py`)
* **Trigger Condition:**
  - 3-candle imbalance gap where Candle 1 High < Candle 3 Low (Bullish FVG) or Candle 1 Low > Candle 3 High (Bearish FVG).
  - Price enters the FVG zone on a pullback.
* **Action:**
  - Trigger when price touches 50% midpoint of the FVG box.
  - SL: Beyond Candle 1 boundary. Target: 1:2 R:R.

### 4.4 SMC Engine 4: Order Block Retest (`smc/smc_module_ob.py`)
* **Trigger Condition:**
  - Last opposing candle before a strong impulsive displacement break.
  - When price subsequently returns and touches the Order Block boundary.
* **Action:**
  - Precise institutional bounce entry.
  - SL: Just beyond OB extreme. Target: 1:2.5 R:R.

### 4.5 Candlestick Price Action Engine (`smc/strategy_candlestick.py`)
* Implement the 23 Masterclass Candlestick Patterns:
  - **Single:** Hammer, Inverted Hammer, Shooting Star, Dragonfly Doji, Gravestone Doji, Marubozu.
  - **Double:** Bullish/Bearish Engulfing, Piercing Line (closing $>50\%$ of prior red body), Dark Cloud Cover (closing $<50\%$ of prior green body), Tweezer Tops & Bottoms (double touch at support/resistance).
  - **Triple:** Morning Star, Evening Star, Three White Soldiers, Three Black Crows.
* **Context & Trend Filter:**
  - Bullish reversal patterns only evaluated near support / swing lows / below VWAP recovery.
  - Bearish reversal patterns only evaluated near resistance / swing highs / above VWAP rejection.
  - Trend-following continuation patterns (Marubozu / Three Soldiers) evaluated in direction of 20 EMA / VWAP.

### 4.6 PDH / PDL Masterclass Engine (`smc/strategy_pdh_pdl.py`)
* Based on Groww Masterclass Ep.3:
  - Calculate `PDH`, `PDL`, and `Mid_50 = (PDH + PDL) / 2`.
  - **Acceptance Mode (Breakout):** 15-min candle closes completely above PDH (Bullish) or below PDL (Bearish). Entry on candle break, SL = opposite side of breakout candle.
  - **Rejection Mode (Sweep Reversal):** 15-min candle wicks past PDH/PDL and closes back inside. Entry = Reversal direction, Target 1 = `Mid_50`, Target 2 = Opposite extreme. Trailing SL via ATR (10, 2).

### 4.7 Multi-Strategy Dispatcher (`smc/multi_strategy_terminal.py`)
* Runs all engines in parallel:
  ```python
  signals = {
      'smc_sweep': scan_smc_sweep(candles, quotes=quotes),
      'smc_mss': scan_smc_mss(candles, quotes=quotes),
      'smc_fvg': scan_smc_fvg(candles, quotes=quotes),
      'smc_ob': scan_smc_ob(candles, quotes=quotes),
      'candlestick': scan_candlestick_signals(candles, quotes=quotes),
      'pdh_pdl': scan_pdh_pdl(candles, quotes=quotes),
      'snr_vwap': scan_snr_vwap(candles, quotes=quotes),
      'orb': scan_orb(candles, quotes=quotes),
      'oi_trap': scan_oi_trap(candles, quotes=quotes),
  }
  ```
* Aggregates active signals. Detects cross-engine alignment to output `confluences` without blocking individual signals.

---

## 5. CODEX EXECUTION STEPS (PHASE 1 - COMPLETED)

To execute this architecture step-by-step with Codex:
1. **Step 1:** Implement `smc/strategy_pdh_pdl.py` and unit tests in `tests/test_strategy_pdh_pdl.py`. [COMPLETED]
2. **Step 2:** Expand `smc/strategy_candlestick.py` to include Morning Star, Evening Star, Piercing Pattern, Dark Cloud Cover, and Tweezer Tops/Bottoms. [COMPLETED]
3. **Step 3:** Implement decoupled SMC modules (`smc/smc_module_sweep.py`, `smc/smc_module_mss.py`, `smc/smc_module_fvg.py`, `smc/smc_module_ob.py`). [COMPLETED]
4. **Step 4:** Integrate all modules into `smc/multi_strategy_terminal.py` with zero blocking. [COMPLETED]
5. **Step 5:** Update UI cards in `smc/app_terminal_v316.py` to render all active strategy cards dynamically. [COMPLETED]
6. **Step 6:** Run `pytest tests/` to verify 100% test pass. [COMPLETED - 675 PASSING]

---

## 6. PHASE 2: FAKE BREAKOUT & TRAP DETECTION SPECIFICATION (EDITION 1.0)
*Reference: NIFTY & SENSEX Fake Breakout & Trap Detection Playbook (November 2026)*

### 6.1 Goal & Constraints
1. **Reduce Over-Trading:** Eliminate 1-minute candle scalp clutter (70+ trades/day) down to **8–10 confirmed A+ trades per day**.
2. **Mathematical Trap Detection:** Identify Bull Traps (buying climax fakeouts) and Bear Traps (selling climax fakeouts) at key levels with strict 5-stage confirmation.
3. **Zero Regression:** All existing 675 unit tests must remain 100% passing. `research_only: True`, `orders_enabled: False`.

### 6.2 Architecture: Event-Driven Candidate Engine (`smc/trap_detector_v1.py`)
Instead of scanning every 1-minute candle, candidate events are triggered ONLY when price interacts with a confirmed structural key level:
* **Key Levels:**
  - `PDH` / `PDL` (Previous Day High / Low)
  - `ORB_H` / `ORB_L` (Opening Range 15M High / Low)
  - `SWING_H` / `SWING_L` (Confirmed 15M Structural Swings)
* **Candidate Crossing Threshold:**
  $$\text{buffer} = \max(0.05 \times \text{ATR}_{5m}(14), \, 2 \times \text{tick\_size})$$
  - Upside Event: $\text{High} > \text{Resistance} + \text{buffer}$
  - Downside Event: $\text{Low} < \text{Support} - \text{buffer}$

### 6.3 Five-Stage Trap & Breakout Verification
1. **Stage 1: Level Sweep:** Price penetrates key level beyond buffer.
2. **Stage 2: Reclaim Window ($K \in \{1, 2, 3\}$ 5-Minute Bars):**
   - Bull Trap: 5M candle body closes back below resistance.
   - Bear Trap: 5M candle body closes back above support.
3. **Stage 3: Market Structure Shift (5M CHOCH with Body Displacement):**
   - Bull Trap: Prior minor 5M swing low is broken with decisive candle close.
   - Bear Trap: Prior minor 5M swing high is broken with decisive candle close.
4. **Stage 4: Retest & Rejection (50% FVG / Order Block):**
   - Pullback to broken level or 50% FVG equilibrium with rejection candle.
5. **Stage 5: Final Execution & Invalidation:**
   - Invalidation SL: Strictly beyond the extreme sweep high/low.
   - Target: Minimum 1:2 R:R toward opposing liquidity.

### 6.4 Label Taxonomy & Output Schema
* `0: NO_TRADE` — Range-bound, ambiguous, or no confirmation (Capital Protection).
* `1: TRUE_UP` — Genuine Bullish Breakout (Consecutive 5M closes above level + hold).
* `2: TRUE_DOWN` — Genuine Bearish Breakdown (Consecutive 5M closes below level + hold).
* `3: BULL_TRAP` — Fake Upside Breakout -> Confirmed Bearish Reversal (PE Candidate).
* `4: BEAR_TRAP` — Fake Downside Breakdown -> Confirmed Bullish Reversal (CE Candidate).

```json
{
  "symbol": "NIFTY",
  "timeframe": "5m",
  "signal_stage": "CONFIRMED_RETEST",
  "candidate_type": "BULL_TRAP",
  "decision_time_ist": "2026-11-20T12:45:00+05:30",
  "level": 25740.0,
  "spot_entry": 25725.0,
  "spot_stop": 25755.0,
  "spot_target": 25665.0,
  "planned_rr": 2.0,
  "model_version": "trap-v1.0",
  "probability": 0.78,
  "status": "ACTIVE"
}
```

### 6.5 Daily Curated Cap (8–10 A+ Trades Filter)
* **Minimum Target Filter:**
  - NIFTY 50: $\ge 40$ index points.
  - SENSEX: $\ge 130$ index points.
* **Minimum R:R:** Strict $\ge 1:2.0$.
* **Wave Cooldown:** 25-minute minimum lockout between trades in the same direction.

---

## 7. CODEX STEP-BY-STEP EXECUTION INSTRUCTIONS FOR PHASE 2

Codex should execute this phase in the following discrete steps:

### Task 1: Core Trap Detector Engine
* **Create:** `smc/trap_detector_v1.py`
* **Implement:**
  - `compute_atr_5m(candles, period=14)`
  - `detect_candidate_events(candles, levels, atr_buffer)`
  - `evaluate_reclaim(event, bars, k_bars=3)`
  - `evaluate_choch(bars, swing_pivots)`
  - `scan_traps_and_breakouts(candles, symbol, quotes=None, now=None)`
* **Create Unit Tests:** `tests/test_trap_detector.py` (synthetic Bull Trap, Bear Trap, True Breakout, Invalidation test cases).
* **Verify:** Run `pytest tests/test_trap_detector.py` -> 100% pass.

### Task 2: Dispatcher & Hero Gate Integration
* **Update:** `smc/multi_strategy_terminal.py`
  - Import `scan_traps_and_breakouts` from `smc.trap_detector_v1`.
  - Add `trap_detector` to independent scanner dictionary.
  - Wire trap alerts into `build_confirmed_hero_setup` (A+ Trap Reversals take top priority if Master Bias or Counter-Trend Exhaustion confirms).
  - Apply the 25-minute wave cooldown and minimum target filter ($\ge 40$ Nifty / $\ge 130$ Sensex) to limit daily recommendations to 8–10 trades.
* **Verify:** Run `pytest tests/test_multi_strategy_terminal.py` -> 100% pass.

### Task 3: Terminal UI Radar & Alert Badges
* **Update:** `smc/app_terminal_v316.py`
  - Add Live Trap Radar status box in `confirmedHeroSection`.
  - Render badges:
    - `⚠️ BULL TRAP DETECTED at [Level]`
    - `⚠️ BEAR TRAP DETECTED at [Level]`
    - `🚀 GENUINE BREAKOUT (TRUE_UP)`
    - `🛡️ NO TRAP / IN RANGE`
* **Verify:** Refresh terminal in browser (`http://127.0.0.1:8765`), verify zero visual regressions.

### Task 4: Full System Regression Suite
* Run `pytest tests/` across all 675+ tests. Ensure 100% pass rate.
* Verify git status and create clean local commit on `main`.


