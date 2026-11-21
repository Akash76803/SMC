"""Unit and Integration Tests for SMC Phase 5.1 Option Research Engine."""
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
import pytest

from smc.option_research_phase51 import (
    OptionCostBreakdown,
    compute_option_transaction_costs,
    audit_all_option_sources,
    resolve_option_contract_symbol,
    find_matching_quote,
    RESEARCH_DIR,
)

ROOT_DIR = Path("E:/Project/SMC")


def test_option_cost_calculation():
    """Verify institutional options brokerage, STT, turnover charges, and GST."""
    # NIFTY 1 lot (25 qty), buy at 100, sell at 120
    costs = compute_option_transaction_costs(
        market="NIFTY",
        lot_size=25,
        num_lots=1,
        buy_price=100.0,
        sell_price=120.0,
        slippage_pts=0.5,
    )
    # Buy turnover = 25 * 100 = 2500
    # Sell turnover = 25 * 120 = 3000
    assert costs.buy_turnover == 2500.0
    assert costs.sell_turnover == 3000.0
    # Brokerage = 40.0 (20 buy + 20 sell)
    assert costs.brokerage == 40.0
    # STT = 0.1% on 3000 = 3.0
    assert costs.stt == 3.0
    # Exchange turnover = 0.05% of 5500 = 2.75
    assert costs.exchange_txn == 2.75
    # GST = 18% of (40 + 2.75) = 18% of 42.75 = 7.695 -> 7.7
    assert pytest.approx(costs.gst, abs=0.1) == 7.70
    # Stamp duty = 0.003% of 2500 = 0.075 -> 0.08
    assert pytest.approx(costs.stamp_duty, abs=0.05) == 0.08
    # Slippage = 0.5 * 25 = 12.5
    assert costs.slippage_cost == 12.5
    # Total points drag
    assert costs.total_cost_points > 2.0  # Approx 2.6 pts drag per lot


def test_quote_matching_and_window_enforcement():
    """Verify nearest quote matching within latency window and rejection of stale quotes."""
    target_dt = datetime.fromisoformat("2026-11-17T11:47:20+05:30")
    quotes = [
        {"trading_symbol": "NIFTY25400CE", "quote_at": "2026-11-17T11:45:00+05:30", "ask": 80.0},  # 140s prior -> Stale
        {"trading_symbol": "NIFTY25400CE", "quote_at": "2026-11-17T11:47:15+05:30", "ask": 85.0},  # 5s prior -> Best
        {"trading_symbol": "NIFTY25400CE", "quote_at": "2026-11-17T11:47:35+05:30", "ask": 86.0},  # 15s after
    ]

    best_q, latency = find_matching_quote(quotes, target_dt, max_window_sec=120)
    assert best_q is not None
    assert best_q["ask"] == 85.0
    assert latency == 5.0

    # Outside window test
    far_dt = datetime.fromisoformat("2026-11-17T12:00:00+05:30")
    no_q, no_lat = find_matching_quote(quotes, far_dt, max_window_sec=120)
    assert no_q is None
    assert no_lat is None


def test_contract_symbol_resolution():
    """Verify strike resolution for ATM, ITM, OTM contracts."""
    available = [
        "NIFTY17NOV2625350CE",
        "NIFTY17NOV2625400CE",
        "NIFTY17NOV2625450CE",
        "NIFTY17NOV2625400PE",
        "NIFTY17NOV2625450PE",
    ]
    # Bullish (Call) with Spot 25410 -> ATM is 25400 CE, ITM is 25350 CE, OTM is 25450 CE
    atm_ce = resolve_option_contract_symbol("NIFTY", 25410.0, "BULLISH", "ATM", "2026-11-17", available)
    assert atm_ce == "NIFTY17NOV2625400CE"

    itm_ce = resolve_option_contract_symbol("NIFTY", 25410.0, "BULLISH", "ITM", "2026-11-17", available)
    assert itm_ce == "NIFTY17NOV2625350CE"

    otm_ce = resolve_option_contract_symbol("NIFTY", 25410.0, "BULLISH", "OTM", "2026-11-17", available)
    assert otm_ce == "NIFTY17NOV2625450CE"


def test_phase51_deliverables_completeness_and_safety():
    """Verify all 10 required deliverables exist, are well-formed, and strictly enforce safety."""
    expected_files = [
        "option_data_audit.json",
        "observed_quote_coverage.csv",
        "smc_option_trade_ledger.csv",
        "option_entry_exit_analysis.md",
        "nifty_option_performance.json",
        "sensex_option_performance.json",
        "premium_sl_target_study.md",
        "regression_test_report.md",
        "forward_shadow_readiness.md",
        "final_decision.json",
    ]
    for fn in expected_files:
        fp = RESEARCH_DIR / fn
        assert fp.exists(), f"Deliverable missing: {fn}"
        assert fp.stat().st_size > 50, f"Deliverable empty: {fn}"

    # Verify final decision gate
    with (RESEARCH_DIR / "final_decision.json").open("r", encoding="utf-8") as f:
        gate = json.load(f)
    assert gate["final_gate_decision"] in ("READY_WITH_DATA_LIMITATIONS", "READY_FOR_OPTION_SHADOW")
    assert gate["safety_constraints"]["orders_enabled"] is False
    assert gate["safety_constraints"]["research_only"] is True
    assert gate["safety_constraints"]["RANGE_SMC_CONFLUENCE_ENABLED"] is False

    # Verify trade ledger integrity
    with (RESEARCH_DIR / "smc_option_trade_ledger.csv").open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        ledger = list(reader)
    assert len(ledger) >= 100
    # Historical trades without quotes must be UNVERIFIABLE, never assumed profitable/losing
    unverifiable_trades = [t for t in ledger if t["verification_status"] == "UNVERIFIABLE"]
    assert len(unverifiable_trades) > 50
    for t in unverifiable_trades:
        assert t["gross_option_points"] in (None, "", "None")
        assert t["net_option_points"] in (None, "", "None")
