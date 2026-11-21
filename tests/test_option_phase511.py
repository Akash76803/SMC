"""Unit and Integration Tests for SMC Phase 5.1.1 Hardening & Execution Accuracy."""
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
import pytest

from smc.option_research_phase511 import (
    CorrectedCostBreakdown,
    compute_corrected_option_costs,
    find_causal_matching_quote,
    EXACT_CONTRACT_LOT_SIZES,
    OUT_DIR_511,
)

ROOT_DIR = Path("E:/Project/SMC")


def test_statutory_charges_and_stt_post_april_2026():
    """Verify that 0.15% STT applies from 1 April 2026, and 0.10% prior."""
    # Pre-April 2026 trade (e.g. 2026-03-25)
    cost_pre = compute_corrected_option_costs(
        market="NIFTY",
        buy_price=100.0,
        sell_price=120.0,
        trade_date="2026-03-25",
        num_lots=1,
        contract_lot_size=65,
    )
    # Sell turnover = 65 * 120 = 7800
    # STT rate should be 0.0010 (0.10%) -> 7.80
    assert cost_pre.stt_rate == 0.0010
    assert cost_pre.stt_amount == 7.80

    # Post-April 2026 trade (e.g. 2026-11-17)
    cost_post = compute_corrected_option_costs(
        market="NIFTY",
        buy_price=100.0,
        sell_price=120.0,
        trade_date="2026-11-17",
        num_lots=1,
        contract_lot_size=65,
    )
    # STT rate must be 0.0015 (0.15%) -> 11.70
    assert cost_post.stt_rate == 0.0015
    assert cost_post.stt_amount == 11.70
    # Difference must be exact
    assert pytest.approx(cost_post.stt_amount - cost_pre.stt_amount, abs=1e-2) == 3.90


def test_exchange_specific_transaction_rates():
    """Verify exchange transaction charges: NSE (0.0505%) vs BSE (0.0500%)."""
    nifty_cost = compute_corrected_option_costs("NIFTY", 100.0, 100.0, "2026-11-17", 1, 100)
    sensex_cost = compute_corrected_option_costs("SENSEX", 100.0, 100.0, "2026-11-17", 1, 100)

    # Total turnover = 20,000 for both
    assert nifty_cost.total_turnover == 20000.0
    assert sensex_cost.total_turnover == 20000.0

    # NSE: 20000 * 0.000505 = 10.10
    assert nifty_cost.exchange_txn_rate == 0.000505
    assert nifty_cost.exchange_txn_amount == 10.10

    # BSE: 20000 * 0.000500 = 10.00
    assert sensex_cost.exchange_txn_rate == 0.000500
    assert sensex_cost.exchange_txn_amount == 10.00


def test_strict_causality_and_no_lookahead_leakage():
    """Verify that quotes in the future are strictly rejected (no lookahead)."""
    decision_dt = datetime.fromisoformat("2026-11-17T14:52:00+05:30")

    quotes = [
        # Quote 1: 10s in the future (relative to decision) -> MUST BE REJECTED
        {"trading_symbol": "SENSEXPE", "quote_at": "2026-11-17T14:52:10+05:30", "ask": 455.0},
        # Quote 2: 3s prior (causal, fresh) -> MUST BE MATCHED
        {"trading_symbol": "SENSEXPE", "quote_at": "2026-11-17T14:51:57+05:30", "ask": 451.0},
        # Quote 3: 80s prior (causal, but stale if max_age is 60s)
        {"trading_symbol": "SENSEXPE", "quote_at": "2026-11-17T14:50:40+05:30", "ask": 448.0},
    ]

    # Matching with max_age=60s
    match_q, latency, status = find_causal_matching_quote(quotes, decision_dt, max_age_seconds=60.0)
    assert match_q is not None
    assert match_q["ask"] == 451.0  # Chose Quote 2, NOT Quote 1 (which was in the future!)
    assert latency == 3.0
    assert status == "CAUSAL_FRESH_QUOTE_MATCHED"

    # If only future quotes exist
    future_only = [{"trading_symbol": "SENSEXPE", "quote_at": "2026-11-17T14:52:05+05:30", "ask": 455.0}]
    f_match, f_lat, f_status = find_causal_matching_quote(future_only, decision_dt, max_age_seconds=60.0)
    assert f_match is None
    assert f_lat is None
    assert f_status == "NO_CAUSAL_QUOTE_AT_OR_BEFORE_DECISION"

    # If only stale quotes exist (> 60s)
    stale_only = [{"trading_symbol": "SENSEXPE", "quote_at": "2026-11-17T14:50:50+05:30", "ask": 448.0}]  # 70s old
    s_match, s_lat, s_status = find_causal_matching_quote(stale_only, decision_dt, max_age_seconds=60.0)
    assert s_match is None
    assert s_lat == 70.0
    assert "QUOTE_STALE" in s_status


def test_phase511_deliverables_and_reconciliation_integrity():
    """Verify Phase 5.1.1 deliverables exist and reconciliation classifications are explicit."""
    expected_files = [
        "corrected_execution_costs.csv",
        "quote_timestamp_audit.csv",
        "option_trade_reconciliation.csv",
        "signal_rejection_analysis.md",
        "shadow_feed_readiness.md",
        "final_test_report.md",
        "final_gate_decision.json",
    ]
    for fn in expected_files:
        fp = OUT_DIR_511 / fn
        assert fp.exists(), f"Phase 5.1.1 deliverable missing: {fn}"
        assert fp.stat().st_size > 50, f"Phase 5.1.1 deliverable empty: {fn}"

    # Verify gate decision
    with (OUT_DIR_511 / "final_gate_decision.json").open("r", encoding="utf-8") as f:
        gate = json.load(f)
    assert gate["final_gate_decision"] == "READY_WITH_DATA_LIMITATIONS"
    assert gate["stt_rate_post_april_2026"] == 0.0015
    assert gate["safety_constraints"]["orders_enabled"] is False

    # Verify trade reconciliation explicit classifications
    with (OUT_DIR_511 / "option_trade_reconciliation.csv").open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        reconciled = list(reader)

    assert len(reconciled) == 2
    rec_17 = [r for r in reconciled if r["session_date"] == "2026-11-17"][0]
    rec_20 = [r for r in reconciled if r["session_date"] == "2026-11-20"][0]

    assert rec_17["reconciliation_classification"] == "UNVERIFIABLE_SAME_BAR_AMBIGUOUS"
    assert rec_17["net_option_points"] in (None, "", "None")

    assert rec_20["reconciliation_classification"] == "EXCLUDED_POST_1515_SESSION_CUTOFF"
    assert rec_20["net_option_points"] in (None, "", "None")
