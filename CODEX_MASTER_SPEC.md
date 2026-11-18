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

## 5. CODEX EXECUTION STEPS

To execute this architecture step-by-step with Codex:
1. **Step 1:** Implement `smc/strategy_pdh_pdl.py` and unit tests in `tests/test_strategy_pdh_pdl.py`.
2. **Step 2:** Expand `smc/strategy_candlestick.py` to include Morning Star, Evening Star, Piercing Pattern, Dark Cloud Cover, and Tweezer Tops/Bottoms.
3. **Step 3:** Implement decoupled SMC modules (`smc/smc_module_sweep.py`, `smc/smc_module_mss.py`, `smc/smc_module_fvg.py`, `smc/smc_module_ob.py`).
4. **Step 4:** Integrate all modules into `smc/multi_strategy_terminal.py` with zero blocking.
5. **Step 5:** Update UI cards in `smc/app_terminal_v316.py` to render all active strategy cards dynamically.
6. **Step 6:** Run `pytest tests/` to verify 100% test pass.

