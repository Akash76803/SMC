# Phase 5.1.1 Hardening & Verification Test Report

- **Reference Commit:** `5f6e3c0`
- **Verification Date:** 2026-11-21
- **Tests Passed:** All unit and regression tests passing.
- **Key Verifications:**
  1. 0.15% STT post-April 2026 verified mathematically.
  2. Exact lot sizes (65 NIFTY, 20 SENSEX) verified from contract records.
  3. Causality verified: future quote matching strictly blocked ($T_{quote} \le T_{decision}$).
  4. Same-bar SL ambiguity classified explicitly as UNVERIFIABLE without assumed P&L.
  5. Post-15:15 observations classified as EXCLUDED_POST_1515_SESSION_CUTOFF.
