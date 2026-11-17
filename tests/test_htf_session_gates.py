from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from smc.htf_session_gates import (
    build_aggregated_htf_bars,
    evaluate_htf_gate,
    evaluate_session_timing_window,
)
from smc.models import Candle

IST = ZoneInfo("Asia/Kolkata")


def make_candle(dt: datetime, base: float = 100.0) -> Candle:
    return Candle(
        timestamp=dt,
        open=base,
        high=base + 2.0,
        low=base - 2.0,
        close=base + 0.5,
        volume=100.0,
    )


def test_htf_aggregation_session_alignment():
    # Create 2 days of 360 1m candles (09:16 to 15:15 IST)
    usable = {}
    for d_idx, day_str in enumerate(["2026-06-01", "2026-06-02"]):
        day_date = datetime(2026, 6, 1 + d_idx, 9, 16, tzinfo=IST)
        bars = [make_candle(day_date + timedelta(minutes=i), base=100.0 + i * 0.1) for i in range(360)]
        usable[day_str] = bars

    all_15m, all_1h = build_aggregated_htf_bars(usable)

    # 2 days * 24 15m bars/day = 48 bars
    assert len(all_15m) == 48
    # 2 days * 6 1H bars/day = 12 bars
    assert len(all_1h) == 12

    # Check first day 15m close timestamps
    assert all_15m[0].timestamp.time() == time(9, 30)
    assert all_15m[1].timestamp.time() == time(9, 45)
    assert all_15m[23].timestamp.time() == time(15, 15)

    # Check first day 1H close timestamps
    assert all_1h[0].timestamp.time() == time(10, 15)
    assert all_1h[1].timestamp.time() == time(11, 15)
    assert all_1h[5].timestamp.time() == time(15, 15)


def test_htf_gate_uses_only_closed_candles():
    day_date = datetime(2026, 6, 1, 9, 16, tzinfo=IST)
    bars = [make_candle(day_date + timedelta(minutes=i)) for i in range(360)]
    all_15m, all_1h = build_aggregated_htf_bars({"2026-06-01": bars})
    ts_15m = [c.timestamp for c in all_15m]
    ts_1h = [c.timestamp for c in all_1h]

    # At 09:25 IST, 0 15m bars are closed -> UNAVAILABLE
    t_0925 = datetime(2026, 6, 1, 9, 25, tzinfo=IST)
    res_15m_early = evaluate_htf_gate("BULLISH", all_15m, ts_15m, t_0925, "15m")
    assert res_15m_early.allowed is False
    assert res_15m_early.state == "UNAVAILABLE"
    assert res_15m_early.closed_htf_bars_count == 0

    # At 09:30 IST, exactly 1 15m bar has closed -> UNAVAILABLE (< 6 bars)
    t_0930 = datetime(2026, 6, 1, 9, 30, tzinfo=IST)
    res_15m_30 = evaluate_htf_gate("BULLISH", all_15m, ts_15m, t_0930, "15m")
    assert res_15m_30.closed_htf_bars_count == 1
    assert res_15m_30.state == "UNAVAILABLE"

    # At 10:14 IST, 0 1H bars are closed
    t_1014 = datetime(2026, 6, 1, 10, 14, tzinfo=IST)
    res_1h_1014 = evaluate_htf_gate("BULLISH", all_1h, ts_1h, t_1014, "1h")
    assert res_1h_1014.closed_htf_bars_count == 0

    # At 10:15 IST, exactly 1 1H bar has closed
    t_1015 = datetime(2026, 6, 1, 10, 15, tzinfo=IST)
    res_1h_1015 = evaluate_htf_gate("BULLISH", all_1h, ts_1h, t_1015, "1h")
    assert res_1h_1015.closed_htf_bars_count == 1


def test_regression_future_candles_cannot_alter_htf_gate():
    """Regression check proving future candles cannot alter an HTF gate decision."""
    usable = {}
    for d_idx, day_str in enumerate(["2026-06-01", "2026-06-02", "2026-06-03"]):
        day_date = datetime(2026, 6, 1 + d_idx, 9, 16, tzinfo=IST)
        bars = [make_candle(day_date + timedelta(minutes=i), base=100.0 + i * 0.2) for i in range(360)]
        usable[day_str] = bars

    all_15m, all_1h = build_aggregated_htf_bars(usable)
    ts_15m = [c.timestamp for c in all_15m]

    confirm_time = datetime(2026, 6, 2, 11, 45, tzinfo=IST)

    # 1. Full 3 days available
    res_full = evaluate_htf_gate("BULLISH", all_15m, ts_15m, confirm_time, "15m")

    # 2. Only candles up to confirm_time provided
    cutoff_bars = [c for c in all_15m if c.timestamp <= confirm_time]
    cutoff_ts = [c.timestamp for c in cutoff_bars]
    res_cutoff = evaluate_htf_gate("BULLISH", cutoff_bars, cutoff_ts, confirm_time, "15m")

    # 3. Future bars heavily corrupted with massive spikes and crashes
    corrupt_bars = list(all_15m)
    for idx, c in enumerate(corrupt_bars):
        if c.timestamp > confirm_time:
            corrupt_bars[idx] = Candle(
                c.timestamp, 999999.0, 9999999.0, 0.01, 1.0, 100.0
            )
    res_corrupt = evaluate_htf_gate("BULLISH", corrupt_bars, ts_15m, confirm_time, "15m")

    # All decisions must be identical
    assert res_full == res_cutoff
    assert res_full == res_corrupt


def test_session_timing_window_boundaries():
    dt_base = datetime(2026, 6, 1, tzinfo=IST)

    # Pre 09:30 -> BLOCKED
    res1 = evaluate_session_timing_window(dt_base.replace(hour=9, minute=20))
    assert res1.allowed is False
    assert res1.status == "PRE_0930"
    assert res1.block_reason == "BLOCKED_SESSION_PRE_0930"

    # Window 1 start: exactly 09:30 -> ALLOWED
    res2 = evaluate_session_timing_window(dt_base.replace(hour=9, minute=30))
    assert res2.allowed is True
    assert res2.status == "IN_WINDOW"

    # Inside Window 1: 10:45 -> ALLOWED
    res3 = evaluate_session_timing_window(dt_base.replace(hour=10, minute=45))
    assert res3.allowed is True

    # Window 1 end: exactly 11:00 -> BLOCKED (half-open [09:30, 11:00))
    res4 = evaluate_session_timing_window(dt_base.replace(hour=11, minute=0))
    assert res4.allowed is False
    assert res4.status == "MIDDAY_1100_1315"
    assert res4.block_reason == "BLOCKED_SESSION_MIDDAY_1100_1315"

    # Midday lunch chop: 12:30 -> BLOCKED
    res5 = evaluate_session_timing_window(dt_base.replace(hour=12, minute=30))
    assert res5.allowed is False
    assert res5.status == "MIDDAY_1100_1315"

    # Window 2 start: exactly 13:15 -> ALLOWED
    res6 = evaluate_session_timing_window(dt_base.replace(hour=13, minute=15))
    assert res6.allowed is True
    assert res6.status == "IN_WINDOW"

    # Inside Window 2: 14:00 -> ALLOWED
    res7 = evaluate_session_timing_window(dt_base.replace(hour=14, minute=0))
    assert res7.allowed is True

    # Window 2 end: exactly 14:45 -> BLOCKED (half-open [13:15, 14:45))
    res8 = evaluate_session_timing_window(dt_base.replace(hour=14, minute=45))
    assert res8.allowed is False
    assert res8.status == "LATE_POST_1445"
    assert res8.block_reason == "BLOCKED_SESSION_LATE_POST_1445"

    # Late session rush: 15:05 -> BLOCKED
    res9 = evaluate_session_timing_window(dt_base.replace(hour=15, minute=5))
    assert res9.allowed is False
    assert res9.status == "LATE_POST_1445"

