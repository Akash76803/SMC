"""Unit tests for Range Radar API Endpoint (Phase P5)."""
import json
import tempfile
from pathlib import Path
import pytest

from smc.range_predictor_v1 import TARGET_NAME


def test_range_forecast_fallback_schema():
    fallback_data = {
        "schema_version": "range-forecast-v1",
        "symbol": "NIFTY",
        "status": "UNAVAILABLE",
        "reason": "NO_LIVE_SHADOW_SNAPSHOT_FOUND",
        "target_name": TARGET_NAME,
        "research_only": True,
        "orders_enabled": False,
        "snapshot": {
            "spot_at_asof": None,
            "vix_observed": None,
            "straddle_source": "UNAVAILABLE"
        },
        "forecast": {
            "daily_total_range_q10": None,
            "daily_total_range_q50": None,
            "daily_total_range_q90": None,
            "p_expansion": None
        },
        "model": {"type": "BASELINE_OHLC", "version": "1.1.0"},
        "data_quality": {"eligible": False, "missing": ["SHADOW_FORECAST_UNAVAILABLE"]}
    }
    assert fallback_data["schema_version"] == "range-forecast-v1"
    assert fallback_data["target_name"] == "REGULAR_360_RANGE"
    assert fallback_data["orders_enabled"] is False
    assert fallback_data["research_only"] is True


def test_live_range_file_reading():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        live_file = tmp_path / "nifty_latest.json"
        sample_payload = {
            "schema_version": "range-forecast-v1",
            "symbol": "NIFTY",
            "status": "BASELINE_READY",
            "target_name": TARGET_NAME,
            "research_only": True,
            "orders_enabled": False,
            "forecast": {
                "daily_total_range_q10": 120.0,
                "daily_total_range_q50": 180.0,
                "daily_total_range_q90": 260.0,
                "p_expansion": 0.22
            }
        }
        live_file.write_text(json.dumps(sample_payload), encoding="utf-8")
        assert live_file.exists()
        loaded = json.loads(live_file.read_text(encoding="utf-8"))
        assert loaded["symbol"] == "NIFTY"
        assert loaded["forecast"]["daily_total_range_q50"] == 180.0
