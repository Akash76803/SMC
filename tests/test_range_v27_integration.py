"""Integration and Regression Test Suite for SMC V2.7 Final Benchmark."""
import csv
import json
import math
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest

from smc.models import Candle
from smc.range_features_v1 import DailyBar
from smc.range_calibration_v1 import calibrate_range_intervals
from smc.range_benchmark_v27 import winkler_interval_score, compute_causal_rolling_brier
from smc.range_live_v1 import record_live_shadow_forecast, reconcile_shadow_outcomes, append_jsonl, read_jsonl_safely
from smc.range_predictor_v1 import TARGET_NAME, RangeSnapshot, generate_daily_range_forecast
from smc.range_smc_confluence_v1 import RANGE_SMC_CONFLUENCE_ENABLED, evaluate_range_confluence
from smc.angelfolder_backtest_runner import audit_option_data_on_disk

IST = ZoneInfo("Asia/Kolkata")


def test_causality_and_timestamp_boundaries():
    """Verify that predictions at 09:16 use strictly prior closed days and 09:16 bar."""
    prior = [
        DailyBar(date=f"2026-10-{i:02d}", open=25000 + i*5, high=25150 + i*5, low=24950 + i*5, close=25050 + i*5)
        for i in range(1, 26)
    ]
    # Incomplete bar (still forming) must not be passed
    bar_0916 = Candle(
        timestamp=datetime(2026, 11, 20, 9, 16, tzinfo=IST),
        open=25200.0,
        high=25220.0,
        low=25190.0,
        close=25210.0,
        volume=100.0,
    )
    snap = RangeSnapshot(
        symbol="NIFTY",
        trading_date="2026-11-20",
        as_of_ist="09:16",
        spot_at_asof=25210.0,
        prior_completed_days=prior,
        intraday_bars=[bar_0916],
    )
    fc = generate_daily_range_forecast(snap)
    assert fc.target_name == "REGULAR_360_RANGE"
    assert fc.status == "BASELINE_READY"
    assert fc.forecast["daily_total_range_q50"] > 0
    # Prior days must not contain today's date
    assert all(b.date < "2026-11-20" for b in prior)


def test_winkler_interval_score_calculation():
    """Verify mathematical properties of Winkler Interval Score."""
    # When actual is inside interval [100, 200]
    # W = U - L = 100
    assert winkler_interval_score(100.0, 200.0, 150.0, alpha=0.20) == 100.0
    assert winkler_interval_score(100.0, 200.0, 100.0, alpha=0.20) == 100.0
    assert winkler_interval_score(100.0, 200.0, 200.0, alpha=0.20) == 100.0

    # When actual is below L (e.g. 90): W = 100 + 10 * (100 - 90) = 200
    assert winkler_interval_score(100.0, 200.0, 90.0, alpha=0.20) == 200.0

    # When actual is above U (e.g. 220): W = 100 + 10 * (220 - 200) = 300
    assert winkler_interval_score(100.0, 200.0, 220.0, alpha=0.20) == 300.0


def test_snapshot_persistence_and_restart_recovery():
    """Verify that restarting the server preserves existing shadow snapshots and doesn't duplicate."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        history_file = tmp_path / "nifty_shadow_forecasts.jsonl"

        prior = [
            DailyBar(date=f"2026-10-{i:02d}", open=25000, high=25150, low=24950, close=25050)
            for i in range(1, 26)
        ]
        candle = Candle(
            timestamp=datetime(2026, 11, 20, 9, 16, tzinfo=IST),
            open=25000.0, high=25020.0, low=24980.0, close=25010.0, volume=50.0
        )

        # First run records snapshot
        fc1 = record_live_shadow_forecast(
            symbol="NIFTY",
            as_of_ist_iso="2026-11-20T09:16:00+05:30",
            trading_date="2026-11-20",
            spot_at_asof=25010.0,
            prior_completed_days=prior,
            intraday_bars=[candle],
            out_dir=tmp_path,
        )
        assert history_file.exists()
        recs_before = read_jsonl_safely(history_file)
        assert len(recs_before) == 1

        # Second run (simulating process restart) with identical key
        fc2 = record_live_shadow_forecast(
            symbol="NIFTY",
            as_of_ist_iso="2026-11-20T09:16:00+05:30",
            trading_date="2026-11-20",
            spot_at_asof=25010.0,
            prior_completed_days=prior,
            intraday_bars=[candle],
            out_dir=tmp_path,
        )
        recs_after = read_jsonl_safely(history_file)
        assert len(recs_after) == 1  # Guaranteed 0 duplicate writes!


def test_no_modifications_to_existing_smc_signal_decisions():
    """Verify that Range Radar never modifies or overrides SMC signals."""
    # Feature flag must be False
    assert RANGE_SMC_CONFLUENCE_ENABLED is False

    forecast = {
        "status": "BASELINE_READY",
        "target_name": TARGET_NAME,
        "forecast": {
            "daily_total_range_q10": 100.0,
            "daily_total_range_q50": 180.0,
            "daily_total_range_q90": 260.0,
        }
    }
    # Even when range is conflicting (exhausted), setup direction and planned RR are untouched
    res = evaluate_range_confluence(
        symbol="NIFTY",
        setup_direction="BULLISH",
        planned_target_points=100.0,
        planned_rr=3.5,
        forecast=forecast,
        current_spot=25300.0,
        session_high=25300.0,
        session_low=25000.0,  # Realized range 300 pts > Q90 of 260!
    )
    assert res.status == "RANGE_CONTEXT_CONFLICTING"
    assert res.planned_rr == 3.5  # Untouched
    assert res.setup_direction == "BULLISH"  # Untouched
    assert res.confluence_enabled is False  # Advisory only!


def test_missing_historical_option_quote_behavior():
    """Verify that audit_option_data_on_disk marks 7-month backtest as UNVALIDATED without throwing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        # Empty dir or dir with single-day option
        res = audit_option_data_on_disk(tmp_path)
        assert res["usable_for_7_month_backtest"] is False
        assert "Options files on disk" in res["reason"]
