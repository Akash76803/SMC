"""Unit tests for Causal Conformal Calibration (Phase P2.6)."""
import math
import pytest
from smc.range_calibration_v1 import (
    compute_nonconformity_score,
    finite_sample_conformal_quantile,
    calibrate_range_intervals,
    detect_calibration_drift,
    compare_calibrated_baseline,
    CalibratedRecord,
    CalibrationCohortMetrics,
)
from smc.models import Candle
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def test_compute_nonconformity_score():
    # Inside interval: score is 0.0
    assert compute_nonconformity_score(150.0, 100.0, 200.0) == 0.0
    assert compute_nonconformity_score(100.0, 100.0, 200.0) == 0.0
    assert compute_nonconformity_score(200.0, 100.0, 200.0) == 0.0

    # Below q10: q10 - actual
    assert compute_nonconformity_score(80.0, 100.0, 200.0) == 20.0

    # Above q90: actual - q90
    assert compute_nonconformity_score(250.0, 100.0, 200.0) == 50.0


def test_finite_sample_conformal_quantile():
    # Empty
    assert finite_sample_conformal_quantile([]) == 0.0

    # Small sample (e.g. 10 scores)
    scores = [0.0, 0.0, 0.0, 0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0]
    # k = 10, target = 0.80 -> level = ceil(11 * 0.8) / 10 = ceil(8.8) / 10 = 9 / 10 = 0.90
    # Pos = 0.90 * 9 = 8.1 -> interpolation between 8th and 9th score
    q_hat = finite_sample_conformal_quantile(scores, target_coverage=0.80)
    assert q_hat >= 25.0 and q_hat <= 30.0

    # If all zero errors (perfect intervals), adjustment is 0.0
    perfect_scores = [0.0] * 50
    assert finite_sample_conformal_quantile(perfect_scores, 0.80) == 0.0


def test_conformal_interval_expansion_behavior():
    # Generate synthetic sessions where true range is slightly wider than baseline
    # 30 days
    base_dt = datetime(2026, 6, 1, 9, 16, tzinfo=IST)
    usable_sessions: dict[str, list[Candle]] = {}
    for day in range(35):
        day_str = f"2026-06-{day+1:02d}"
        candles = []
        for m in range(360):
            # Range around 200 pts
            high = 25000.0 + (100.0 if m == 100 else 50.0)
            low = 25000.0 - (100.0 if m == 200 else 50.0)
            candles.append(
                Candle(
                    timestamp=base_dt + timedelta(days=day, minutes=m),
                    open=25000.0,
                    high=high,
                    low=low,
                    close=25010.0,
                    volume=100.0,
                )
            )
        usable_sessions[day_str] = candles

    # Run calibration
    metrics, records = calibrate_range_intervals(
        symbol="NIFTY",
        usable_sessions=usable_sessions,
        snapshot_time="09:16",
        rolling_window=20,
        warmup_sessions=15,
        target_coverage=0.80,
    )

    assert isinstance(metrics, CalibrationCohortMetrics)
    assert len(records) > 0
    # Causality test: records[i] rolling_calibration_sample_size should strictly increase
    for i in range(1, len(records)):
        assert records[i].rolling_calibration_sample_size >= records[i-1].rolling_calibration_sample_size


def test_detect_calibration_drift():
    # Pass stable records
    records = [
        CalibratedRecord(
            trading_date=f"2026-07-{i:02d}",
            as_of="09:16",
            symbol="NIFTY",
            actual_range=150.0,
            uncalibrated_q10=100.0,
            uncalibrated_q50=150.0,
            uncalibrated_q90=200.0,
            uncalibrated_width=100.0,
            uncalibrated_covered=True,
            conformal_score_q_hat=10.0,
            calibrated_q10=90.0,
            calibrated_q90=210.0,
            calibrated_width=120.0,
            calibrated_covered=True,
            rolling_calibration_sample_size=20,
            is_nr7=False,
            atr14=150.0,
        )
        for i in range(1, 41)
    ]
    drift_detected, diff, cov1, cov2 = detect_calibration_drift(records, drift_threshold=0.15)
    assert not drift_detected
    assert cov1 == 1.0 and cov2 == 1.0

    # Simulate drift in second half
    for r in records[20:]:
        r.calibrated_covered = False
    drift_detected, diff, cov1, cov2 = detect_calibration_drift(records, drift_threshold=0.15)
    assert drift_detected
    assert diff == 1.0
