"""Unit and Integration Tests for SMC V2.7.1 Trade Reconciliation & Final Audit."""
import csv
import json
from pathlib import Path
import pytest

from smc.range_smc_confluence_v1 import RANGE_SMC_CONFLUENCE_ENABLED

ROOT_DIR = Path("E:/Project/SMC")
V271_DIR = ROOT_DIR / "results" / "range_forecast" / "v271"


def test_v271_artifacts_generated_and_valid():
    """Verify all 8 v271 artifacts exist and are well-formed."""
    expected_files = [
        "trade_level_reconciliation.csv",
        "ab_discrepancy_analysis.md",
        "corrected_smc_ab_comparison.csv",
        "statistical_validation.json",
        "live_shadow_readiness.md",
        "regression_test_report.md",
        "final_gate_decision.json",
        "final_summary.md",
    ]
    for fn in expected_files:
        fpath = V271_DIR / fn
        assert fpath.exists(), f"Missing required artifact: {fn}"
        assert fpath.stat().st_size > 50, f"Artifact {fn} is empty or too small"

    # Verify JSON files can be parsed
    with open(V271_DIR / "final_gate_decision.json", "r", encoding="utf-8") as f:
        gate_dec = json.load(f)
    assert gate_dec["final_decision"] == "READY_FOR_LIVE_SHADOW"
    assert gate_dec["component_decisions"]["SMC_RANGE_FILTERING"] == "ADVISORY_ONLY_HARD_FILTERING_PROHIBITED"
    assert RANGE_SMC_CONFLUENCE_ENABLED is False

    with open(V271_DIR / "statistical_validation.json", "r", encoding="utf-8") as f:
        stats = json.load(f)
    assert stats["NIFTY"]["matched_sample_size"] == 129
    assert stats["SENSEX"]["matched_sample_size"] == 129
    assert stats["NIFTY"]["conformal"]["coverage_80pct"] >= 0.80
    assert stats["SENSEX"]["conformal"]["coverage_80pct"] >= 0.80


def test_reconciled_trade_ledger_math_identities():
    """Verify that trade ledger reconciliation satisfies exact mathematical identities."""
    csv_file = V271_DIR / "trade_level_reconciliation.csv"
    assert csv_file.exists()

    with open(csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        ledger = list(reader)

    assert len(ledger) == 99  # 25 NIFTY + 74 SENSEX

    # Filter by market
    nifty_trades = [t for t in ledger if t["market"] == "NIFTY"]
    sensex_trades = [t for t in ledger if t["market"] == "SENSEX"]
    assert len(nifty_trades) == 25
    assert len(sensex_trades) == 74

    # SENSEX check
    sensex_a = [t for t in sensex_trades if t["strategy_a_eligible"] == "True"]
    sensex_b = [t for t in sensex_trades if t["strategy_b_eligible"] == "True"]
    sensex_rej = [t for t in sensex_trades if t["strategy_b_eligible"] == "False"]

    assert len(sensex_a) == 74
    assert len(sensex_b) == 54
    assert len(sensex_rej) == 20

    # Avoided losses and missed winners
    avoided_losses = [t for t in sensex_rej if float(t["gross_index_points"]) < 0]
    missed_winners = [t for t in sensex_rej if float(t["gross_index_points"]) > 0]
    assert len(avoided_losses) == 15
    assert len(missed_winners) == 5

    # Check sum of avoided losses and missed winners across both markets
    total_avoided_losses = len([t for t in ledger if t["strategy_b_eligible"] == "False" and float(t["gross_index_points"]) < 0])
    total_missed_winners = len([t for t in ledger if t["strategy_b_eligible"] == "False" and float(t["gross_index_points"]) > 0])
    assert total_avoided_losses == 17
    assert total_missed_winners == 7

    # Exact delta identity: PnL(A) - PnL(B) == sum(rejected_trades_points)
    sum_a = sum(float(t["gross_index_points"]) for t in sensex_a)
    sum_b = sum(float(t["gross_index_points"]) for t in sensex_b)
    sum_rej = sum(float(t["gross_index_points"]) for t in sensex_rej)
    assert pytest.approx(sum_a - sum_b, abs=1e-2) == sum_rej
    assert pytest.approx(sum_rej, abs=1e-1) == 177.0  # +176.99 pts

    # SENSEX Holdout exact check
    sensex_holdout_rej = [t for t in sensex_rej if t["split"] == "Holdout"]
    assert len(sensex_holdout_rej) == 2
    assert all(float(t["gross_index_points"]) > 0 for t in sensex_holdout_rej)
    sum_holdout_rej = sum(float(t["gross_index_points"]) for t in sensex_holdout_rej)
    assert pytest.approx(sum_holdout_rej, abs=1e-1) == 219.7  # +219.73 pts
