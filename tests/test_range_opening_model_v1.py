"""Unit tests for 09:30 Opening Range Model (Phase P3.1)."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pytest

from smc.models import Candle
from smc.range_features_v1 import DailyBar
from smc.range_opening_model_v1 import (
    extract_0930_opening_features,
    compute_opening_targets,
    run_opening_model_experiment,
    OpeningFeaturesRecord,
    OpeningTargetsRecord,
)

IST = ZoneInfo("Asia/Kolkata")


def make_test_session():
    base_dt = datetime(2026, 6, 15, 9, 16, tzinfo=IST)
    session_candles = []
    # 09:16 to 09:30 = 15 candles
    # spot starts at 25000, high at 25050, low at 24980, close at 25020 at 09:30
    for i in range(15):
        session_candles.append(
            Candle(
                timestamp=base_dt + timedelta(minutes=i),
                open=25000.0 if i == 0 else 25010.0,
                high=25050.0 if i == 5 else 25020.0,
                low=24980.0 if i == 8 else 24990.0,
                close=25020.0 if i == 14 else 25010.0,
                volume=100.0,
            )
        )
    # Remaining candles until 15:15 (345 candles)
    for i in range(15, 360):
        # High reaches 25150 at i=100, Low drops to 24920 at i=200
        session_candles.append(
            Candle(
                timestamp=base_dt + timedelta(minutes=i),
                open=25020.0,
                high=25150.0 if i == 100 else 25050.0,
                low=24920.0 if i == 200 else 25000.0,
                close=25040.0,
                volume=100.0,
            )
        )
    return session_candles


def test_extract_0930_opening_features():
    session = make_test_session()
    prior_days = [
        DailyBar(date=f"2026-05-{i:02d}", open=24900, high=25100, low=24850, close=25000)
        for i in range(1, 26)
    ]
    feats = extract_0930_opening_features(
        symbol="NIFTY",
        trading_date="2026-06-15",
        session_candles=session,
        prior_days=prior_days,
    )
    assert isinstance(feats, OpeningFeaturesRecord)
    assert feats.symbol == "NIFTY"
    assert feats.trading_date == "2026-06-15"
    assert feats.spot_at_0930 == 25020.0
    assert feats.open_15m_range == 70.0  # 25050 - 24980
    assert feats.open_15m_range > 0.0
    assert feats.atr14 > 0.0


def test_compute_opening_targets():
    session = make_test_session()
    targets = compute_opening_targets(
        symbol="NIFTY",
        trading_date="2026-06-15",
        session_candles=session,
        spot_at_0930=25020.0,
    )
    assert isinstance(targets, OpeningTargetsRecord)
    # Total range: high 25150 - low 24920 = 230.0
    assert targets.target_a_total_range == 230.0
    # Remaining upside: max_high_after_0930 (25150) - spot_0930 (25020) = 130.0
    assert targets.target_b_remaining_up == 130.0
    # Remaining downside: spot_0930 (25020) - min_low_after_0930 (24920) = 100.0
    assert targets.target_c_remaining_down == 100.0


def test_opening_model_insufficient_bars_fallback():
    # Only 5 bars provided
    base_dt = datetime(2026, 6, 15, 9, 16, tzinfo=IST)
    short_session = [
        Candle(
            timestamp=base_dt + timedelta(minutes=i),
            open=25000.0,
            high=25010.0,
            low=24990.0,
            close=25005.0,
            volume=100.0,
        )
        for i in range(5)
    ]
    prior_days = [
        DailyBar(date=f"2026-05-{i:02d}", open=24900, high=25100, low=24850, close=25000)
        for i in range(1, 26)
    ]
    feats = extract_0930_opening_features(
        symbol="NIFTY",
        trading_date="2026-06-15",
        session_candles=short_session,
        prior_days=prior_days,
    )
    assert feats is None
