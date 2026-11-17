# MULTI-STRATEGY INTRADAY TRADING SYSTEM PLAN
**Target Workspace:** `e:\Project\SMC`
**Objective:** Add modular S&R + VWAP, ORB (15m), and Option Chain (OI) Trapping engines alongside existing SMC without breaking any existing code or tests.

---

## CRITICAL RULES FOR CODEX:
1. **DO NOT MODIFY** existing core SMC files (`smc/angel_dual_stream_v318.py`, `smc/ict_lifecycle_v316.py`, `smc/live_candles_v312.py`, `smc/live_bracket_v318.py`).
2. Implement new strategies as **independent, isolated modules** under `smc/`.
3. Every new module must have unit tests.
4. Existing 462 pytest unit tests must continue to pass 100%: `pytest tests/`.
5. Provide actionable ATM, ITM, and OTM strikes with premium entry, SL, and Target for Angel One execution.

---

## ARCHITECTURE & PHASES:

### Phase 1: Strike & Greeks Engine (`smc/option_strike_engine.py`)
- Input: Current Index Spot price, Option quotes stream (`results/live_nifty_option_quotes.jsonl`).
- Output: 
  - `ATM`: nearest strike, premium entry, premium SL = Index SL * 0.50, Target = Index Target * 0.50.
  - `ITM`: 1 strike in-the-money, premium SL = Index SL * 0.65, Target = Index Target * 0.65.
  - `OTM`: 1 strike out-of-the-money, premium SL = Index SL * 0.35, Target = Index Target * 0.35.

### Phase 2: S&R + VWAP Rejection Strategy (`smc/strategy_snr_vwap.py`)
- Key Levels: Previous Day High (PDH), Previous Day Low (PDL), Day High/Low, Dynamic VWAP.
- Entry Trigger:
  - Long: Price retests Support/VWAP + Bullish Pinbar/Hammer on 5-min candle.
  - Short: Price retests Resistance/VWAP + Bearish Shooting Star on 5-min candle.
- Index SL: Below swing low / resistance candle wick (8 to 15 index pts).
- Index Target: Next S&R level or 1:2 Risk-Reward minimum.

### Phase 3: Opening Range Breakout (15m ORB) (`smc/strategy_orb.py`)
- Key Range: 09:15 to 09:30 AM high & low.
- Entry Trigger: 09:30 AM नंतर 5-min candle ORB Range च्या बाहेर क्लोज + व्हॉल्युम सपोर्ट.
- Retest Entry: ब्रेकआउट नंतर ORB लेव्हल रिटेस्ट करताना एन्ट्री.
- SL: ORB Range Mid-point किंवा ब्रेकआउट कँडलचा लो/हाय.

### Phase 4: Option Chain & OI Trap (`smc/strategy_oi_trap.py`)
- Key Data: Max Call OI Strike & Max Put OI Strike from live options snapshot.
- Short Covering Trigger: जर स्पॉट इंडेक्स Max Call OI च्या वर १५ मिनिटे टिकला -> Call Unwinding -> Bullish Momentum.
- Long Unwinding Trigger: जर स्पॉट इंडेक्स Max Put OI च्या खाली घसरला -> Put Unwinding -> Bearish Momentum.

### Phase 5: Dashboard Integration (`smc/app_terminal_v316.py` & HTML)
- Expose `/api/multi_strategy_status` returning signals from all 4 engines.
- Add front-end cards with instant "Copy Strike & Premium" for Angel One mobile app.

