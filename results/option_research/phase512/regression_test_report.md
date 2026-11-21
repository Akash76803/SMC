# Regression Test Report — Phase 5.1.2 Hardened & Frozen

Generated: 2026-11-21T18:07:30+05:30

## Test Execution Summary

| Suite / Checkpoint | Tests Passed | Tests Skipped | Tests Failed |
|--------------------|-------------|---------------|--------------|
| 1d23963 (Phase 5.1.1 baseline) | 742 | 2 | 0 |
| Phase 5.1.2 Initial Commit (`1ac88c6`) | 798 | 2 | 0 |
| **Phase 5.1.2 Safety Hardened (Final)** | **837** | **2** | **0** |

## Test Breakdown by Category

1. **Phase 5.1.2 Core Market Data Corrections (`test_option_phase512.py`)**: 56 passed
   - WebSocket Mode Constants: LTP=1, QUOTE=2, SNAP_QUOTE=3, DEPTH=4 verified
   - Session Calendar: Research window (09:16–15:15), MIS window (15:15–15:20), Closing auction (15:20–15:30), Exchange close (15:30)
   - Timestamp Layering: 5 independent causal fields (exchange_ms, broker_quote, local_recv, signal, sim_exec)
   - Quality Gates: Stale quote rejection (>60s), thin-market rejection (qty=0), wide-spread gate (>3%)
   - Statutory Fee Model: STT 0.15% from 1 April 2026, NSE NFO 0.0505%, BSE BFO 0.0500%, GST 18%, Brokerage flat ₹20

2. **Phase 5.1.2 Minimal Safety Fixes (`test_shadow_safety_v512.py`)**: 39 passed
   - Holiday Detection: NSE 2026 official calendar + weekend gate + next trading day logic
   - EOD Reconciliation Logging: Automated 15:15 atomic JSON logging for quote tapes, live signals, and paper portfolio
   - Persistent Quote Deduplication: File-backed cross-restart deduplication checkpoint

3. **Core SMC Range & Engine Regression Suite**: 742 passed, 2 skipped
   - All historical replay, range conformal calibration, Winkler interval scoring, and SMC A/B benchmarks remain 100% green without regressions.

## Safety Invariant Verification

```python
assert ORDERS_ENABLED is False
assert RESEARCH_ONLY is True
assert RANGE_SMC_CONFLUENCE_ENABLED is False
```
All safety invariants are strictly enforced in every module and validated by automated tests.
