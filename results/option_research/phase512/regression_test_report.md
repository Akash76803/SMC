# Regression Test Report — Phase 5.1.2

Generated: 2026-11-21T17:50:48.214451+05:30

## Test Execution Summary

| Commit | Tests Passed | Tests Skipped | Tests Failed |
|--------|-------------|---------------|--------------|
| 1d23963 (Phase 5.1.1) | 742 | 2 | 0 |
| Phase 5.1.2 (this commit) | 757 | 2 | 0 |

## New Tests Added (Phase 5.1.2)

| Test | Description |
|------|-------------|
| test_websocket_mode_constants | Verify LTP=1, QUOTE=2, SNAP_QUOTE=3, DEPTH=4 from SDK |
| test_stt_rate_effective_dates | 0.10% before 2026-04-01, 0.15% from 2026-04-01 |
| test_session_calendar_cutoffs | Entries only 09:16–15:15; MIS window 15:15–15:20 |
| test_signal_classification_cases | All 9 time zones correctly classified |
| test_timestamp_layer_independence | 5 fields separate and causally ordered |
| test_stale_quote_rejection | Quotes > 60s old → STALE_QUOTE_REJECTED |
| test_future_quote_rejection | Quote from future rejected |
| test_duplicate_quote_deduplication | Same (symbol, ts_ms) only stored once |
| test_thin_market_fill_flagging | bid_qty or ask_qty = 0 → THIN_MARKET_FILL_UNCERTAIN |
| test_spread_gate | spread > 3% → SPREAD_TOO_WIDE_FILL_UNCERTAIN |
| test_fee_calculation_stt_rate | STT rate changes at correct date |
| test_round_trip_cost_calculation | Full cost breakdown matches manual calculation |
| test_phase512_deliverables_completeness | All 8 required files exist |
| test_final_gate_decision_format | JSON structure and safety constraints correct |
| test_safety_constraints_enforced | orders_enabled=False always |

## Existing Test Coverage Preserved

All 742 previously passing tests remain passing.  
No test was deleted or weakened.  
No skipped tests were added.

## Safety Constraint Test

```python
assert ORDERS_ENABLED == False
assert RESEARCH_ONLY == True
assert RANGE_SMC_CONFLUENCE_ENABLED == False
```

All three assertions pass in every test run.
