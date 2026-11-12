from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from dataclasses import dataclass
import pytest
from smc.models import Candle,IndexSetup,Side
from smc.multiday_replay import validate_hourly,replay_by_session,group_days,final_sweep_audit
from smc.historical_replay import ReplayConfig
import smc.multiday_replay as module
from smc.backtest import BacktestConfig,Signal,walk_forward_backtest
IST=ZoneInfo("Asia/Kolkata")
def bar(day,minute,value=100):
    t=datetime(2026,11,day,9,16,tzinfo=IST)+timedelta(minutes=minute)
    return Candle(t,value,value+2,value-2,value)
def hour(day,hour):
    t=datetime(2026,11,day,hour,15,tzinfo=IST)
    return Candle(t,100,102,98,100)

def test_partial_hourly_excluded():
    h=[hour(9,h) for h in range(9,16)]
    full,drop=validate_hourly(h,[bar(11,0)],60)
    assert drop==1
    assert [x.timestamp.hour for x in full]==[9,10,11,12,13,14]
def test_bad_hourly_alignment_and_interval():
    with pytest.raises(ValueError,match="60_MINUTE"):
        validate_hourly([hour(9,9)],[bar(11,0)],30)
    broken=Candle(datetime(2026,11,9,9,30,tzinfo=IST),100,102,98,100)
    with pytest.raises(ValueError,match="ALIGNED"):
        validate_hourly([broken],[bar(11,0)],60)
def test_groups_days_and_no_overnight_replay():
    ltf=[bar(11,0),bar(11,1),bar(12,0),bar(12,1)]
    assert [n for _,_,n in group_days(ltf)]==[0,2]
    h=[hour(9,9),hour(9,10),hour(9,11),hour(9,12),hour(9,13),hour(9,14)]
    result=replay_by_session(ltf,h,ReplayConfig("NIFTY"))
    assert len(result.sessions)==2
    assert result.trades==()
    assert len(result.snapshots)==2
def test_unique_sweeps_are_not_repeated_prefix_observations():
    result,records=final_sweep_audit([bar(11,i) for i in range(18)],"NIFTY")
    assert sum(result.values())==len(records)
    assert records==()
def test_replay_call_scoped_to_each_session(monkeypatch):
    ltf=[bar(11,i) for i in range(4)]+[bar(12,i) for i in range(4)]
    h=[hour(9,h) for h in range(9,15)]
    sizes=[]
    def fake_run(bars,engine,config):
        sizes.append(len(bars))
        return walk_forward_backtest(bars,lambda prefix:None,config)
    monkeypatch.setattr(module,"walk_forward_backtest",fake_run)
    result=replay_by_session(ltf,h,ReplayConfig("NIFTY"))
    assert sizes==[4,4]
    assert len(result.sessions)==2
