from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import pytest
from smc.data_quality import audit_1m,drop_terminal_1530
from smc.models import Candle
IST=ZoneInfo("Asia/Kolkata")
def bar(h,m,day=11):
    t=datetime(2026,11,day,h,m,tzinfo=IST)
    return Candle(t,100,101,99,100)
def test_observed_nifty_isolated_close():
    candles=[bar(9,16),bar(9,17),bar(15,15),bar(15,30)]
    a=audit_1m(candles)
    assert a.safe_for_replay is False
    assert any(x.code=="TERMINAL_1530_UNCLASSIFIED" and x.missing==14 for x in a.issues)
    # Dropping terminal does not hide the earlier real gap.
    b=audit_1m(drop_terminal_1530(candles))
    assert b.safe_for_replay is False
    assert any(x.code=="INTRADAY_GAP" for x in b.issues)
def test_full_continuous_session_with_terminal_drop():
    start=datetime(2026,11,11,9,16,tzinfo=IST)
    candles=[Candle(start+timedelta(minutes=i),100,101,99,100) for i in range(360)]
    candles.append(bar(15,30))
    a=audit_1m(candles)
    assert len(a.issues)==1 and a.issues[0].missing==14
    cleaned=drop_terminal_1530(candles)
    assert len(cleaned)==360
    assert audit_1m(cleaned).safe_for_replay
def test_no_fabricated_candles_or_cross_day_issue():
    bars=[bar(9,16,11),bar(9,17,11),bar(9,16,12),bar(9,17,12)]
    q=audit_1m(bars)
    assert q.safe_for_replay and q.days==2
    assert len(drop_terminal_1530(bars))==4
def test_random_gap_is_rejected():
    q=audit_1m([bar(9,16),bar(9,19)])
    assert not q.safe_for_replay
    assert q.issues[0].missing==2
def test_session_start_unknown_is_flagged():
    q=audit_1m([bar(10,16),bar(10,17)])
    assert q.issues[0].code=="SESSION_START_UNVERIFIED"
def test_duplicates_refused():
    with pytest.raises(ValueError):
        audit_1m([bar(9,16),bar(9,16)])
