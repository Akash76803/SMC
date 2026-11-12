from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from smc.models import Candle
from smc.research_sessions import regular_november_2026,regular_htf_without_special
from smc.data_quality import audit_1m
IST=ZoneInfo("Asia/Kolkata")
def bar(day,h,m):
    return Candle(datetime(2026,11,day,h,m,tzinfo=IST),100,101,99,100)
def test_profile_handles_both_1529_and_1530():
    candles=[bar(2,9,16),bar(2,9,17),bar(2,15,29),
             bar(8,14,21),bar(8,14,22),
             bar(9,9,16),bar(9,9,17),bar(9,15,30)]
    cleaned=regular_november_2026(candles)
    assert cleaned.removed_special==2
    assert cleaned.removed_closing_tail==2
    assert len(cleaned.candles)==4
    assert audit_1m(cleaned.candles).safe_for_replay
def test_all_360_valid_bars_preserved():
    first=datetime(2026,11,2,9,16,tzinfo=IST)
    seq=[Candle(first+timedelta(minutes=i),100,101,99,100) for i in range(360)]
    result=regular_november_2026(seq+[bar(2,15,30)])
    assert result.candles==tuple(seq)
    assert result.removed_closing_tail==1
    assert audit_1m(result.candles).safe_for_replay
def test_nov8_hourly_excluded_but_regular_remains():
    assert regular_htf_without_special([bar(6,9,15),bar(8,14,15),
                                        bar(9,9,15)])==(
                                           bar(6,9,15),bar(9,9,15))
def test_early_start_not_silently_purged():
    raw=[bar(2,9,12),bar(2,9,16)]
    assert not audit_1m(regular_november_2026(raw).candles).safe_for_replay
