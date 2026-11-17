from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from smc.models import Candle
from smc.sentiment_classifier import classify_intraday_sentiment

IST = ZoneInfo("Asia/Kolkata")


def make_candle(idx: int, open_: float, high: float, low: float, close: float, base_time: datetime | None = None) -> Candle:
    if base_time is None:
        base_time = datetime(2026, 6, 1, 9, 16, tzinfo=IST)
    ts = base_time + timedelta(minutes=idx)
    return Candle(
        timestamp=ts,
        open=float(open_),
        high=float(high),
        low=float(low),
        close=float(close),
        volume=100.0,
    )


def test_fewer_than_30_bars_returns_unavailable():
    bars = [make_candle(i, 100, 105, 95, 100) for i in range(25)]
    res = classify_intraday_sentiment(bars, confirm_index=24)
    assert res.sentiment == "UNAVAILABLE"
    assert "FEWER_THAN_30_BARS" in res.reason
    assert res.bars_available == 25


def test_gap_in_30_bar_window_returns_unavailable():
    bars = []
    base = datetime(2026, 6, 1, 9, 16, tzinfo=IST)
    for i in range(35):
        # Insert a 5-minute gap at index 20
        extra_min = 5 if i >= 20 else 0
        ts = base + timedelta(minutes=i + extra_min)
        bars.append(Candle(ts, 100.0, 105.0, 95.0, 100.0, 50.0))

    # At confirm_index 30, the window[-30:] includes the jump at index 20
    res = classify_intraday_sentiment(bars, confirm_index=30)
    assert res.sentiment == "UNAVAILABLE"
    assert "INTRADAY_GAP_IN_30_BARS" in res.reason


def test_bullish_sentiment():
    # 30 bars: older 15 bars in range [100, 110], latest bar closes at 115
    bars = []
    for i in range(15):
        bars.append(make_candle(i, 100, 110, 95, 105))
    for i in range(15, 29):
        bars.append(make_candle(i, 105, 112, 104, 108))
    # latest bar (index 29) closes above 110 (high of older 15 bars)
    bars.append(make_candle(29, 108, 116, 107, 115))

    res = classify_intraday_sentiment(bars, confirm_index=29)
    assert res.sentiment == "BULLISH"
    assert res.older_high == 110.0
    assert res.older_low == 95.0
    assert res.latest_close == 115.0
    assert "ABOVE_OLDER_15_HIGH" in res.reason


def test_bearish_sentiment():
    # older 15 bars in range [100, 110], latest bar closes at 90 (< min low 95)
    bars = []
    for i in range(15):
        bars.append(make_candle(i, 100, 110, 95, 105))
    for i in range(15, 29):
        bars.append(make_candle(i, 105, 106, 94, 96))
    bars.append(make_candle(29, 96, 96, 89, 90))

    res = classify_intraday_sentiment(bars, confirm_index=29)
    assert res.sentiment == "BEARISH"
    assert res.older_high == 110.0
    assert res.older_low == 95.0
    assert res.latest_close == 90.0
    assert "BELOW_OLDER_15_LOW" in res.reason


def test_mixed_sentiment_inside_range_and_boundaries():
    # older 15 bars: low=95, high=110
    bars = [make_candle(i, 100, 110, 95, 102) for i in range(15)]
    bars += [make_candle(i, 100, 108, 98, 102) for i in range(15, 29)]

    # 1. strictly inside
    bars_inside = list(bars) + [make_candle(29, 102, 106, 101, 104)]
    res_inside = classify_intraday_sentiment(bars_inside, confirm_index=29)
    assert res_inside.sentiment == "MIXED"

    # 2. at upper boundary (close == 110)
    bars_top = list(bars) + [make_candle(29, 108, 110, 107, 110)]
    res_top = classify_intraday_sentiment(bars_top, confirm_index=29)
    assert res_top.sentiment == "MIXED"

    # 3. at lower boundary (close == 95)
    bars_bot = list(bars) + [make_candle(29, 98, 98, 95, 95)]
    res_bot = classify_intraday_sentiment(bars_bot, confirm_index=29)
    assert res_bot.sentiment == "MIXED"


def test_regression_lookahead_zero_leakage():
    """Verify that candles after confirm_index cannot alter the sentiment classification."""
    # Build 100 continuous 1m bars
    base = datetime(2026, 6, 1, 9, 16, tzinfo=IST)
    bars = []
    for i in range(100):
        # Up to bar 40: normal trading around 100
        bars.append(Candle(base + timedelta(minutes=i), 100.0, 105.0, 95.0, 101.0, 100.0))

    # At bar 40 (confirmation): make bar 40 close at 120 (bullish breakout above older 15 high 105)
    bars[40] = Candle(bars[40].timestamp, 105.0, 122.0, 104.0, 120.0, 200.0)

    # 1. Evaluate with full 100 bars
    res_full = classify_intraday_sentiment(bars, confirm_index=40)

    # 2. Evaluate with only bars up to confirmation (41 bars: 0..40)
    res_sliced = classify_intraday_sentiment(bars[:41], confirm_index=40)

    # 3. Mutate future bars 41..99 with wild crashes, huge spikes, and corrupt timestamps
    bars_mutated = list(bars)
    for j in range(41, 100):
        bars_mutated[j] = Candle(
            bars[j].timestamp + timedelta(days=10),
            99999.0, 999999.0, 0.01, 0.05, 1.0
        )
    res_mutated = classify_intraday_sentiment(bars_mutated, confirm_index=40)

    # All three must produce the exact identical sentiment and numbers
    assert res_full.sentiment == "BULLISH"
    assert res_full == res_sliced
    assert res_full == res_mutated

