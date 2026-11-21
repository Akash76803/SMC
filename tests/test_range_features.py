"""Unit tests for range_features_v1."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from smc.models import Candle
from smc.range_features_v1 import (
    DailyBar,
    compute_atr,
    compute_gap,
    compute_nr7,
    compute_realized_volatility,
    compute_true_range,
    extract_opening_features,
)

IST = ZoneInfo("Asia/Kolkata")


def test_true_range_calculations():
    # Case 1: Normal bar within prior close
    # High=105, Low=95, Prior Close=100 -> Max(10, 5, 5) = 10
    assert compute_true_range(105, 95, 100) == 10.0
    
    # Case 2: Gap up, Low above prior close
    # High=115, Low=105, Prior Close=100 -> Max(10, 15, 5) = 15
    assert compute_true_range(115, 105, 100) == 15.0
    
    # Case 3: Gap down, High below prior close
    # High=90, Low=80, Prior Close=100 -> Max(10, 10, 20) = 20
    assert compute_true_range(90, 80, 100) == 20.0


def test_atr_history_requirement_and_values():
    bars = [
        DailyBar(date=f"2026-11-{i:02d}", open=100, high=110, low=90, close=100)
        for i in range(1, 15)  # 14 bars
    ]
    # Insufficient bars: period 14 requires 15 bars (14 TRs against prior close)
    assert compute_atr(bars, period=14) is None
    
    # Add 15th bar
    bars.append(DailyBar(date="2026-11-15", open=100, high=110, low=90, close=100))
    atr14 = compute_atr(bars, period=14)
    assert atr14 is not None
    assert round(atr14, 2) == 20.0  # (110 - 90 = 20 every day)


def test_nr7_tie_breaking_and_causality():
    # 7 completed daily bars
    # Day 1-6 ranges: 50, 40, 45, 60, 55, 35
    # Day 7 range: 30 (strictly lowest)
    bars = [
        DailyBar(date=f"2026-11-0{i}", open=100, high=100 + r, low=100, close=100 + r/2)
        for i, r in enumerate([50, 40, 45, 60, 55, 35, 30], start=1)
    ]
    assert compute_nr7(bars) is True
    
    # Day 7 tied with lowest (35 and 35)
    bars[-1] = DailyBar(date="2026-11-07", open=100, high=135, low=100, close=110)
    # Tie rule: 35 <= min(50, 40, 45, 60, 55, 35) is True!
    assert compute_nr7(bars) is True
    
    # Day 7 larger than minimum (42 > 35)
    bars[-1] = DailyBar(date="2026-11-07", open=100, high=142, low=100, close=110)
    assert compute_nr7(bars) is False


def test_opening_features_0916_and_0930():
    base_dt = datetime(2026, 11, 20, 9, 16, tzinfo=IST)
    candles = [
        Candle(
            timestamp=base_dt + timedelta(minutes=i),
            open=25000.0 + i * 2,
            high=25010.0 + i * 2,
            low=24990.0 + i * 2,
            close=25005.0 + i * 2,
            volume=100.0,
        )
        for i in range(15)  # 09:16 through 09:30
    ]
    prior_close = 24950.0
    
    # 09:16 snapshot
    f16 = extract_opening_features("09:16", candles, prior_close, atr14=150.0)
    assert f16.as_of == "09:16"
    assert f16.spot_at_asof == 25005.0
    assert f16.gap_points == 50.0  # 25000 - 24950
    assert f16.open_15m_range is None
    
    # 09:30 snapshot
    f30 = extract_opening_features("09:30", candles, prior_close, atr14=150.0)
    assert f30.as_of == "09:30"
    assert f30.spot_at_asof == candles[-1].close
    assert f30.open_15m_high == max(c.high for c in candles)
    assert f30.open_15m_low == min(c.low for c in candles)
    assert f30.open_15m_range == f30.open_15m_high - f30.open_15m_low
    assert f30.open_range_atr_ratio == round(f30.open_15m_range / 150.0, 3)
