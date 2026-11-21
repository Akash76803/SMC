"""Unit tests for Range Predictor Data Safety and Protected Architecture (Section 2 & 10)."""
import pytest
from smc.range_predictor_v1 import (
    generate_daily_range_forecast,
    RangeSnapshot,
    TARGET_NAME,
)
from smc.range_features_v1 import DailyBar
from smc.range_smc_confluence_v1 import RANGE_SMC_CONFLUENCE_ENABLED


def test_no_synthetic_option_bid_ask():
    # If no real option quote is provided, straddle_source must be UNAVAILABLE or real, never fabricated
    prior = [
        DailyBar(date=f"2026-10-{i:02d}", open=25000, high=25150, low=24950, close=25050)
        for i in range(1, 26)
    ]
    snapshot = RangeSnapshot(
        symbol="NIFTY",
        trading_date="2026-11-20",
        as_of_ist="09:16",
        spot_at_asof=25000.0,
        prior_completed_days=prior,
        intraday_bars=[],
        vix_observed=None,
    )
    fc = generate_daily_range_forecast(snapshot)
    assert fc.orders_enabled is False
    assert fc.research_only is True
    assert fc.snapshot.get("straddle_source") == "UNAVAILABLE"
    # Straddle metrics must be None, NOT synthetic numbers
    assert fc.forecast.get("straddle_implied_range") is None
    assert fc.forecast.get("straddle_raw_pts") is None


def test_protected_feature_flags():
    # Verify protected flags
    assert RANGE_SMC_CONFLUENCE_ENABLED is False


def test_deterministic_baseline_reproducibility():
    prior = [
        DailyBar(date=f"2026-10-{i:02d}", open=25000 + i*5, high=25150 + i*5, low=24950 + i*5, close=25050 + i*5)
        for i in range(1, 26)
    ]
    snapshot1 = RangeSnapshot(
        symbol="NIFTY",
        trading_date="2026-11-20",
        as_of_ist="09:16",
        spot_at_asof=25100.0,
        prior_completed_days=prior,
        intraday_bars=[],
    )
    snapshot2 = RangeSnapshot(
        symbol="NIFTY",
        trading_date="2026-11-20",
        as_of_ist="09:16",
        spot_at_asof=25100.0,
        prior_completed_days=prior,
        intraday_bars=[],
    )
    fc1 = generate_daily_range_forecast(snapshot1)
    fc2 = generate_daily_range_forecast(snapshot2)

    assert fc1.forecast["daily_total_range_q10"] == fc2.forecast["daily_total_range_q10"]
    assert fc1.forecast["daily_total_range_q50"] == fc2.forecast["daily_total_range_q50"]
    assert fc1.forecast["daily_total_range_q90"] == fc2.forecast["daily_total_range_q90"]
    assert fc1.forecast["p_expansion"] == fc2.forecast["p_expansion"]
    assert fc1.target_name == "REGULAR_360_RANGE"
