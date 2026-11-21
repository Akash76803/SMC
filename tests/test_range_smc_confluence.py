"""Unit tests for SMC Structure and Range Forecast Confluence (Phase P6)."""
import pytest
from smc.range_smc_confluence_v1 import (
    evaluate_range_confluence,
    RangeConfluenceAnnotation,
    RANGE_SMC_CONFLUENCE_ENABLED,
)
from smc.range_predictor_v1 import TARGET_NAME


def test_confluence_disabled_by_default():
    # Protected constraint: flag must be False by default
    assert RANGE_SMC_CONFLUENCE_ENABLED is False


def test_range_unavailable_handling():
    res = evaluate_range_confluence(
        symbol="NIFTY",
        setup_direction="BULLISH",
        planned_target_points=60.0,
        planned_rr=2.0,
        forecast=None,
        current_spot=25000.0,
        session_high=25020.0,
        session_low=24980.0,
    )
    assert isinstance(res, RangeConfluenceAnnotation)
    assert res.status == "RANGE_CONTEXT_UNAVAILABLE"
    assert res.is_target_within_room is True
    assert res.exhaustion_risk is False


def test_range_supportive_when_target_fits_well():
    forecast = {
        "status": "BASELINE_READY",
        "target_name": TARGET_NAME,
        "forecast": {
            "daily_total_range_q10": 100.0,
            "daily_total_range_q50": 180.0,
            "daily_total_range_q90": 260.0,
        }
    }
    # Current range so far: 40 pts (25020 - 24980). Q50 is 180. Remaining room = 140 pts.
    # Planned target is 50 pts, well within remaining room.
    res = evaluate_range_confluence(
        symbol="NIFTY",
        setup_direction="BULLISH",
        planned_target_points=50.0,
        planned_rr=2.0,
        forecast=forecast,
        current_spot=25000.0,
        session_high=25020.0,
        session_low=24980.0,
    )
    assert res.status == "RANGE_CONTEXT_SUPPORTIVE"
    assert res.is_target_within_room is True
    assert res.exhaustion_risk is False
    assert res.range_room_remaining == 220.0


def test_range_conflicting_when_exhaustion_risk_and_target_exceeds_band():
    forecast = {
        "status": "BASELINE_READY",
        "target_name": TARGET_NAME,
        "forecast": {
            "daily_total_range_q10": 100.0,
            "daily_total_range_q50": 180.0,
            "daily_total_range_q90": 260.0,
        }
    }
    # Current range so far: 270 pts (already exceeded Q90 of 260!). Remaining room = 0.
    # Planned target is 60 pts.
    res = evaluate_range_confluence(
        symbol="NIFTY",
        setup_direction="BULLISH",
        planned_target_points=60.0,
        planned_rr=2.0,
        forecast=forecast,
        current_spot=25250.0,
        session_high=25250.0,
        session_low=24980.0,
    )
    assert res.status == "RANGE_CONTEXT_CONFLICTING"
    assert res.is_target_within_room is False
    assert res.exhaustion_risk is True
    assert res.range_room_remaining == 0.0


def test_rr_constraint_is_preserved():
    forecast = {
        "status": "BASELINE_READY",
        "target_name": TARGET_NAME,
        "forecast": {
            "daily_total_range_q10": 100.0,
            "daily_total_range_q50": 180.0,
            "daily_total_range_q90": 260.0,
        }
    }
    # If setup planned_rr is 2.0, confluence layer NEVER changes it or forces 3.0
    res = evaluate_range_confluence(
        symbol="NIFTY",
        setup_direction="BEARISH",
        planned_target_points=50.0,
        planned_rr=2.0,
        forecast=forecast,
        current_spot=25000.0,
        session_high=25030.0,
        session_low=24990.0,
    )
    assert res.planned_rr == 2.0
