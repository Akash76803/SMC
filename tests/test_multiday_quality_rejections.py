from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import pytest
from smc.multiday_replay import validate_hourly
from smc.historical_replay import ReplaySnapshot
from smc.models import Candle
IST=ZoneInfo("Asia/Kolkata")
def bar(h,m,day=9):
    t=datetime(2026,11,day,h,m,tzinfo=IST)
    return Candle(t,100,102,98,100)
def test_missing_full_hour_is_rejected():
    missing=[bar(h,15) for h in (9,10,11,13,14)]
    with pytest.raises(ValueError,match="HTF_MISSING"):
        validate_hourly(missing,[bar(9,16,day=11)],60)
def test_six_full_hours_with_partial_terminal():
    full=[bar(h,15) for h in range(9,16)]
    valid,excluded=validate_hourly(full,[bar(9,16,day=11)],60)
    assert len(valid)==6 and excluded==1
def test_risk_details_are_optional():
    s=ReplaySnapshot(None,"WAIT","NO_SWEEP_SETUP",1,1)
    assert s.rejection_detail is None
