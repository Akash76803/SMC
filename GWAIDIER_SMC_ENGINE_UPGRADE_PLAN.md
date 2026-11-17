# GWAIDIER SMC ENGINE UPGRADE PLAN (PRO-TREND & COUNTER-PULLBACK WITH HTF/LTF CONFLUENCE)
**Target:** Clean, non-invasive upgrade of the SMC Engine based on Gwaidier SMC Lecture #6 (POI & Entry Module) and Lecture #11 (Fractals, Dealing Range & Market Structure).
**Author/Architect:** Antigravity (Google DeepMind)
**Target Executor:** Codex / Developer
**Strict Constraint:** ONLY SMC engine files may be modified (`smc/ict_lifecycle_v316.py`, `smc/live_research_v312.py`, `smc/live_setup_screen_v317.py`, `smc/app_terminal_v316.py`, tests). ZERO changes to broker auth, order execution, options strike engine, or risk limits. Research/Paper mode ONLY (`orders_enabled: False`).

---

## 🎯 ARCHITECTURAL OVERVIEW & OBJECTIVES

### The 3 Core Problems with Current Implementation:
1. **Rigid 11-Item Checklist:** The terminal blocks valid setups because it expects 11 independent items (including live broker Greeks and quotes) before transitioning out of `WAIT / NO TRADE`.
2. **Hard-Rejection of Counter-Trades:** Setups where Bullish OB is in Premium or Bearish OB is in Discount are outright discarded as `REJECTED_WRONG_ZONE`, ignoring Gwaidier's **Internal Range / Counter-Pullback** trades.
3. **Missing HTF/LTF Decoupling:** Gwaidier explicitly separates **HTF Context (15m/1H POIs)** from **LTF Triggers (1m/5m Displacement + FVG + Retest)**. Current code conflated them on a single 1-minute stream.

### The Upgraded Model:
```
[ 1. HTF CONTEXT (15m / 1H) ]
   ├── Dealing Range: Confirmed High, Confirmed Low, 50% Equilibrium
   ├── Position: DISCOUNT (< 50%) or PREMIUM (> 50%)
   └── 5 Valid POIs Only:
         • POI 1: IDM Sweep (IFSC Candle - wick only)
         • POI 2: Decisional OB (First OB immediately below/above IDM)
         • POI 3: Extreme OB (Near CHoCH origin / Last Line of Defense)
         • POI 4: BOS Sweep (External liquidity grab → triggers Counter-Pullback)
         • POI 5: CHoCH Sweep (Major trend reversal sweep)
         (ALL intermediate "middle" Order Blocks are classified as TRAP and ignored)
                │
                ▼
[ 2. LTF TRIGGER (1m / 5m) ]
   ├── Step 1: Liquidity Sweep / Trap (SL hunt of retail buyers/sellers)
   ├── Step 2: Displacement (Elephant in pool: MSS + FVG or Volume Imbalance)
   └── Step 3: Mitigation Retest (Entry trigger at FVG/OB; SL at protected swing)
                │
                ▼
[ 3. TRADE CLASSIFICATION & TARGETING ]
   ├── PRO_TREND: Aligned with HTF Zone (Bullish in Discount, Bearish in Premium)
   │     └── Target: HTF Major BOS / External Liquidity (1:3+ R:R)
   └── COUNTER_PULLBACK: Counter to HTF Zone (triggered by BOS/High/Low sweep)
         └── Target: Strictly HTF 50% Equilibrium or First Internal FVG/OB
```

---

## 📁 TARGET FILES & MODIFICATIONS

| File | Proposed Changes |
| :--- | :--- |
| `smc/ict_lifecycle_v316.py` | 1. Support `setup_type = "PRO_TREND"` vs `"COUNTER_PULLBACK"`.<br>2. Add `poi_category`: `IDM_SWEEP`, `DECISIONAL_OB`, `EXTREME_OB`, `BOS_SWEEP`, `TRAP_IGNORED`.<br>3. Detect **Volume Imbalance** (wick-to-wick overlap with no candle body) in addition to FVG.<br>4. Retain backward compatibility (`state="REJECTED_WRONG_ZONE"` preserved when `allow_counter=False`). |
| `smc/live_research_v312.py` | 1. Extract HTF Dealing Range from `1h` (fallback to `15m` if 1h has < 2 pivots).<br>2. Pass HTF context + Dealing Range into `scan_ict_lifecycles(..., allow_counter=True)`.<br>3. Expose `htf_context` and `setup_type` in live report payload. |
| `smc/live_setup_screen_v317.py` | 1. Replace 11-item checklist with **Gwaidier 3-Confluence Matrix**:<br>   - Confluence 1: HTF Context & POI (Discount/Premium, Valid POI)<br>   - Confluence 2: LTF Trap & Displacement (MSS + FVG/Volume Imbalance)<br>   - Confluence 3: Retest / Execution Bracket (Entry close, Protected SL, Target)<br>2. Do not block index research when live broker option Greeks are absent. |
| `smc/app_terminal_v316.py` | 1. Render the simplified 3-Confluence Checklist.<br>2. Display badge: `PRO-TREND (BOS TARGET)` vs `COUNTER-PULLBACK (50% EQ TARGET)`.<br>3. Display HTF Dealing Range (High, Low, 50% Eq) clearly on the header. |
| `tests/test_gwaidier_confluence.py` | Dedicated test suite verifying 5 POIs, Volume Imbalance, Counter-Pullback targeting, and 3-confluence transitions. |

---

## 🛠️ STEP-BY-STEP IMPLEMENTATION TASKS FOR CODEX

### TASK 1: Upgrade `smc/ict_lifecycle_v316.py`
1. **Detect Volume Imbalance:**
   ```python
   def find_volume_imbalances(candles: list[Candle]) -> list[Zone]:
       """Wick-to-wick gap where price traded without candle bodies (Lecture 6)."""
       # For bullish: candle[i-2].high < candle[i].low and no bodies overlap in the gap
       # Acts as an FVG for institutional retests.
   ```
2. **POI Classification:**
   - Classify OBs based on position relative to IDM:
     - If OB is immediately adjacent to IDM $\rightarrow$ `DECISIONAL_OB`.
     - If OB is near structural origin/CHoCH $\rightarrow$ `EXTREME_OB`.
     - Intermediate OBs $\rightarrow$ `TRAP_MIDDLE_OB` (flagged so they do not trigger premature entries).
3. **Counter-Pullback State & Invalidation:**
   - When `dealing_range` is supplied:
     - If `_zone_aligned(direction, ob_zone_label)` is `True` $\rightarrow$ `setup_type = "PRO_TREND"`. Target = External BOS.
     - If `_zone_aligned(direction, ob_zone_label)` is `False`:
       - If `allow_counter=True`: Do NOT set `REJECTED_WRONG_ZONE`. Set `setup_type = "COUNTER_PULLBACK"`, `state = "WAITING_FOR_RETEST"`, and set provisional target to `dealing_range["equilibrium"]`.
       - If `allow_counter=False`: Retain existing `REJECTED_WRONG_ZONE` for legacy test compatibility.

### TASK 2: Upgrade `smc/live_research_v312.py`
1. **HTF Reference Fallback (1H $\rightarrow$ 15M):**
   - In intraday morning sessions (09:15 - 11:15 IST), 1H pivots may not be confirmed yet.
   - If `tf_1h` lacks confirmed high/low, fallback to `tf_15m` confirmed pivots!
   - Construct `dealing_range`:
     ```python
     dealing_range = {
         "timeframe": selected_tf,  # "1h" or "15m"
         "high": htf_high,
         "low": htf_low,
         "equilibrium": (htf_high + htf_low) / 2.0,
         "position": position,
         "source": f"{selected_tf.upper()}_CONFIRMED_PIVOTS",
     }
     ```
2. **Pass `allow_counter=True`:**
   - Call `lifecycles = scan_ict_lifecycles(candles, dealing_range=dealing_range, allow_counter=True)`.

### TASK 3: Simplify Setup Screen (`smc/live_setup_screen_v317.py`)
1. **Consolidate Missing Evidence into 3 Core Confluences:**
   - **Confluence 1 (HTF POI):** `HTF_POI_VALIDATED` (Valid POI identified, not a middle trap).
   - **Confluence 2 (Displacement):** `DISPLACEMENT_CONFIRMED` (MSS + FVG or Volume Imbalance present).
   - **Confluence 3 (Retest & Bracket):** `MITIGATION_RETEST` (Clean retest with valid index bracket).
2. **Remove Unrealistic Checklist Blockers:**
   - Stop hardcoding `LIVE_OPTION_BID_ASK_GREEKS` and `EXECUTABLE_ENTRY_PRICE` into the index setup screen `missing_evidence` list.
   - Clearly separate **Index Structural Setup (Pass/Wait)** from **Option Pricing (Available/Unavailable)**.

### TASK 4: Update Terminal Dashboard (`smc/app_terminal_v316.py`)
1. **Update Confirmation Checklist UI:**
   - Display the 3 Core Gwaidier Confluences prominently:
     - 🟢 `HTF Zone & POI (Decisional / Extreme / Sweep)`
     - 🟢 `LTF Displacement (MSS + FVG / Volume Imbalance)`
     - 🟢 `Mitigation Retest & Bracket`
2. **Display Trade Type Badge:**
   - Show `[PRO-TREND]` in green with target BOS.
   - Show `[COUNTER-PULLBACK]` in amber with target 50% Equilibrium.

---

## 🧪 VERIFICATION & ACCEPTANCE CRITERIA FOR CODEX

Codex must verify the implementation by running these exact commands in PowerShell:

### Test 1: Full Regression Check
```powershell
& .venv\Scripts\pytest.exe -q
```
* **Acceptance:** All 624+ existing tests MUST PASS with 0 errors.

### Test 2: Gwaidier Unit Tests
```powershell
& .venv\Scripts\pytest.exe tests/test_ict_lifecycle_v316.py -v
```
* **Acceptance:** All lifecycle tests pass, including backward-compatible zone filter and new counter-pullback tests.

### Test 3: Live Real-Data Dry Run
```powershell
& .venv\Scripts\python.exe -c "
import json
from smc.models import Candle
from smc.ict_lifecycle_v316 import scan_ict_lifecycles

with open('results/live_nifty.jsonl', 'r') as f:
    for line in f:
        data = json.loads(line)
        if 'sampled_live_candles' in data:
            candles = [Candle.from_dict(c) for c in data['sampled_live_candles']]
            dr = {'equilibrium': 25420.0, 'low': 25300.0, 'high': 25540.0, 'position': 'DISCOUNT'}
            rows = scan_ict_lifecycles(candles, dealing_range=dr, allow_counter=True)
            pro = [r for r in rows if r.get('setup_type') == 'PRO_TREND']
            counter = [r for r in rows if r.get('setup_type') == 'COUNTER_PULLBACK']
            print(f'PRO_TREND setups: {len(pro)}, COUNTER_PULLBACK setups: {len(counter)}')
            break
"
```
* **Acceptance:** Successfully identifies setups classified into `PRO_TREND` and `COUNTER_PULLBACK` without crashes.

---

## 🔒 SAFETY & REVERSION PROTOCOL
- If any test breaks, Codex must NOT modify non-SMC files.
- Revert via Git:
  ```powershell
  git checkout feature/smc-gwaidier-fractal-upgrade
  git status
  ```
- `.env` must NEVER be modified or staged.

