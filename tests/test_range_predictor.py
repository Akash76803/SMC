"""Unit tests for range_predictor_v1."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from smc.models import Candle
from smc.range_features_v1 import DailyBar
from smc.range_predictor_v1 import RangeSnapshot, generate_daily_range_forecast

IST = ZoneInfo("Asia/Kolkata")


def test_forecast_data_insufficient_when_no_history():
    snap = RangeSnapshot(
        symbol="NIFTY",
        trading_date="2026-11-20",
        as_of_ist="2026-11-20T09:16:00+05:30",
        spot_at_asof=25000.0,
        prior_completed_days=[],  # Empty!
    )
    fc = generate_daily_range_forecast(snap)
    assert fc.status == "DATA_INSUFFICIENT"
    assert "INSUFFICIENT_TRAINING_SESSIONS" in fc.data_quality["missing"]
    assert fc.forecast["daily_total_range_q50"] is None
    assert fc.research_only is True
    assert fc.orders_enabled is False


def test_forecast_baseline_ready_with_daily_history():
    # 25 prior days
    prior = [
        DailyBar(
            date=f"2026-10-{i:02d}",
            open=25000.0,
            high=25150.0,
            low=24950.0,
            close=25050.0,
        )
        for i in range(1, 26)
    ]
    snap = RangeSnapshot(
        symbol="NIFTY",
        trading_date="2026-11-20",
        as_of_ist="2026-11-20T09:16:00+05:30",
        spot_at_asof=25100.0,
        prior_completed_days=prior,
    )
    fc = generate_daily_range_forecast(snap)
    assert fc.status == "BASELINE_READY"
    assert fc.model["type"] == "BASELINE_OHLC"
    assert fc.forecast["daily_total_range_q50"] is not None
    assert fc.forecast["daily_total_range_q10"] < fc.forecast["daily_total_range_q50"] < fc.forecast["daily_total_range_q90"]
    assert fc.forecast["p_expansion"] is not None
    assert fc.research_only is True
    assert fc.orders_enabled is False


def test_forecast_schema_contract_compliance():
    prior = [
        DailyBar(date=f"2026-10-{i:02d}", open=25000, high=25150, low=24950, close=25050)
        for i in range(1, 26)
    ]
    snap = RangeSnapshot(
        symbol="NIFTY",
        trading_date="2026-11-20",
        as_of_ist="2026-11-20T09:16:00+05:30",
        spot_at_asof=25100.0,
        prior_completed_days=prior,
    )
    fc = generate_daily_range_forecast(snap)
    dumped = json.loads(fc.to_json())
    
    # Verify exact schema keys from spec Page 13
    assert dumped["schema_version"] == "range-forecast-v1"
    assert dumped["symbol"] == "NIFTY"
    assert dumped["session_definition"] == "REGULAR_360"
    assert dumped["research_only"] is True
    assert dumped["orders_enabled"] is False
    assert "spot_at_asof" in dumped["snapshot"]
    assert "daily_total_range_q50" in dumped["forecast"]
    assert "p_upper_touch" in dumped["forecast"]
    assert "eligible" in dumped["data_quality"]
    assert "snapshot_digest" in dumped["data_quality"]
    assert dumped["data_quality"]["snapshot_digest"].startswith("sha256:")
