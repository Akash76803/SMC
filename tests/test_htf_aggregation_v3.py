from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from smc.models import Candle
from smc.htf_aggregation_v3 import aggregate_regular_1m

IST=ZoneInfo("Asia/Kolkata")

def session(day=11):
    start=datetime(2026,11,day,9,16,tzinfo=IST)
    return [
        Candle(start+timedelta(minutes=i),100+i,102+i,99+i,101+i,volume=2)
        for i in range(360)
    ]

def test_one_complete_regular_session():
    s=session()
    x=aggregate_regular_1m(s)
    assert len(x.bars_5m)==72
    assert len(x.bars_15m)==24
    assert len(x.bars_1h)==6
    assert len(x.daily)==1
    assert x.weekly==() and x.monthly==()

def test_all_htf_stamps_are_final_close():
    s=session()
    x=aggregate_regular_1m(s)
    assert x.bars_5m[0].timestamp==s[4].timestamp
    assert x.bars_15m[0].timestamp==s[14].timestamp
    assert x.bars_1h[0].timestamp==s[59].timestamp
    assert x.bars_1h[-1].timestamp==s[-1].timestamp
    assert x.daily[0].timestamp==s[-1].timestamp

def test_ohlc_and_volume_aggregate():
    s=session()
    x=aggregate_regular_1m(s)
    first=x.bars_5m[0]
    assert (first.open,first.high,first.low,first.close,first.volume)==(
        100,106,99,105,10)

def test_no_partial_daily_candle():
    with pytest.raises(ValueError,match="INCOMPLETE_REGULAR_SESSION"):
        aggregate_regular_1m(session()[:-1])

def test_internal_gap_not_fabricated():
    s=session()
    with pytest.raises(ValueError,match="LTF_QUALITY_GATE_FAILED"):
        aggregate_regular_1m(s[:4]+s[5:])

def test_no_unverified_weekly_or_monthly_inference():
    s=session()
    x=aggregate_regular_1m(s)
    assert x.weekly==() and x.monthly==()

def test_explicit_period_end_required_and_time_is_close():
    s=session()
    x=aggregate_regular_1m(
        s,verified_week_ends=frozenset({"2026-11-11"}),
        verified_month_ends=frozenset({"2026-11-11"}))
    assert x.weekly[0].timestamp==s[-1].timestamp
    assert x.monthly[0].timestamp==s[-1].timestamp

def test_unobserved_week_end_refused():
    with pytest.raises(ValueError,match="UNOBSERVED_CALENDAR_PERIOD_END"):
        aggregate_regular_1m(
            session(),verified_week_ends=frozenset({"2026-11-13"}))

def test_incomplete_source_rejected():
    s=session()
    x=s[2]
    s[2]=Candle(x.timestamp,x.open,x.high,x.low,x.close,complete=False)
    with pytest.raises(ValueError,match="INCOMPLETE_1M_SOURCE"):
        aggregate_regular_1m(s)

def test_mixed_two_sessions_counts():
    data=session(11)+session(12)
    x=aggregate_regular_1m(data)
    assert len(x.daily)==2 and len(x.bars_1h)==12
    assert x.weekly==()

def test_empty_rejected():
    with pytest.raises(ValueError,match="NO_1M_SOURCE"):
        aggregate_regular_1m([])
