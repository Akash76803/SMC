# SMC Phase 5.1 — Option Entry/Exit Quality & Quote Analysis

## 1. Executive Summary
This research evaluates the real-world execution feasibility and pricing quality of SMC trading setups using observed Angel One option quote tapes (`results/live_*_option_quotes.jsonl`).

### Key Empirical Findings:
- **Quote Feed Nature:** The recorded quotes are periodic REST API polling snapshots (~15-20s interval), NOT true exchange tick-by-tick streams. Liquid ATM/ITM bid/ask quotes exhibit excellent tightness (median spread < 0.25%).
- **Historical Quote Void:** Historical 1-minute files on disk cover only a single session (`2026-11-11`), and the 7-8 month backtest lacks order book depth. Exactly **97 baseline trades are marked UNVERIFIABLE** to avoid fabricating synthetic fills.
- **Observed Live Execution:** In the 4 recorded live sessions (`2026-11-17` to `2026-11-20`), SENSEX produced 2 confirmed SMC trades. On `2026-11-17T14:53`, valid liquid quotes existed across ATM, ITM, and OTM strikes.

## 2. Friction & Slippage Impact
Standard Indian options statutory charges (₹40 round-trip brokerage, 0.1% STT on sell side, exchange txn, GST, stamp duty) impose a fixed hurdle of ₹55-65 per lot (~2.2 to 2.6 premium points for NIFTY, ~5.5 to 6.5 premium points for SENSEX). This confirms that short scalps (< 10 points) suffer excessive friction decay.
