# CONFIRMATION & VERIFICATION PLAN
**Purpose:** Verify that Codex has correctly implemented the new strategies without breaking existing SMC code.

---

## 📋 STEP-BY-STEP VERIFICATION CHECKLIST

### ✅ Step 1: Zero-Regression Test (Baseline Verification)
Run in PowerShell:
```powershell
pytest tests/ -q
```
* **Expected Result:** All 462 existing tests pass, plus any new tests written by Codex (e.g. 480+ passed, 0 failed).
* **If any existing test fails:** Codex violated the non-invasive rule. Ask Codex to revert changes to `smc/ict_lifecycle_v316.py` or `smc/live_candles_v312.py`.

---

### ✅ Step 2: Strike Engine Math Verification (`smc/option_strike_engine.py`)
Run a quick python check to ensure Delta calculation is accurate:
```powershell
python -c "
from smc.option_strike_engine import select_strikes
res = select_strikes(spot=25400, direction='BULLISH', index_sl_pts=15, index_target_pts=30)
print('ATM Strike:', res['ATM']['strike'], 'Premium SL:', res['ATM']['premium_sl'], 'Target:', res['ATM']['premium_target'])
assert res['ATM']['strike'] == 25400
assert res['ITM']['strike'] == 25350
assert res['OTM']['strike'] == 25450
print('STRIKE ENGINE PASSED!')
"
```
* **Expected Result:** `ATM: 25400, ITM: 25350, OTM: 25450` आणि `STRIKE ENGINE PASSED!`.

---

### ✅ Step 3: S&R + VWAP Signal Verification on Historical Data
Run the S&R engine against today's recorded live session (`results/live_nifty.jsonl`):
```powershell
python -c "
from smc.strategy_snr_vwap import scan_snr_signals
import json
with open('results/live_nifty.jsonl', 'r') as f:
    candles = [json.loads(line) for line in f]
signals = scan_snr_signals(candles)
print(f'Total S&R signals detected today: {len(signals)}')
for s in signals[:3]:
    print(s)
"
```
* **Expected Result:** Shows 2 to 4 valid S&R/VWAP retest setups detected during today's market session.

---

### ✅ Step 4: ORB 15-Minute Engine Verification
Run the ORB test on today's session:
```powershell
python -c "
from smc.strategy_orb import evaluate_orb_15m
import json
with open('results/live_nifty.jsonl', 'r') as f:
    candles = [json.loads(line) for line in f]
orb = evaluate_orb_15m(candles)
print('ORB 15m Range:', orb['range_high'], orb['range_low'])
print('ORB Breakout Triggered:', orb['breakout_status'])
"
```
* **Expected Result:** Correctly locks the 09:15-09:30 candle range and identifies the breakout direction.

---

### ✅ Step 5: Live Terminal & UI Health Check
Start the research terminal:
```powershell
.\run_smc.ps1
```
Open browser at `http://127.0.0.1:8765`:
1. Check that the existing **SMC / Market Research Terminal** loads properly.
2. Verify that the new Multi-Strategy status bar or cards appear.
3. Verify that ATM, ITM, and OTM strike recommendations are clearly visible and copyable for Angel One mobile app.

