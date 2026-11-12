from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from smc.models import Side
from smc.phase6_premium import Quote,Signal,Settings,replay
import pytest
T=datetime(2026,11,11,10,0,tzinfo=ZoneInfo("Asia/Kolkata"))
def q(sec,bid,ask,side=Side.CE):
    return Quote(T+timedelta(seconds=sec),"NIFTY",side,25000,T+timedelta(days=2),
                 bid,ask,65,100)
def s(side=Side.CE):
    return Signal(T,"NIFTY",side,"BOS_FVG_CONTINUATION")
def test_no_same_candle_lookahead_and_observed_bid():
    trades,skipped=replay([s()],[q(0,99,100),q(60,99,100),q(120,140,141)])
    assert len(trades)==1
    assert trades[0].entry_time==T+timedelta(seconds=60)
    assert trades[0].exit_bid==140
    assert trades[0].net_per_unit==39
def test_observed_stop_not_fabricated_threshold():
    trades,_=replay([s()],[q(60,99,100),q(120,84,86)])
    assert trades[0].exit_reason=="STOP_OBSERVED_BID"
    assert trades[0].net_per_unit==-17
def test_missing_quotes_no_fake_profit():
    trades,skips=replay([s()],[])
    assert trades==[] and skips["NO_FRESH_LIQUID_QUOTE"]==1
def test_quote_gap_not_filled():
    trades,skips=replay([s()],[q(60,99,100),q(400,140,141)])
    assert trades==[] and skips["UNOBSERVABLE_QUOTE_GAP"]==1
def test_wrong_option_side():
    trades,skips=replay([s(Side.PE)],[q(60,99,100),q(120,140,141)])
    assert trades==[] and skips["NO_FRESH_LIQUID_QUOTE"]==1
def test_rr_uses_cost():
    with pytest.raises(ValueError,match="NET_PREMIUM_RR_BELOW_2"):
        Settings(target_points=20,stop_points=10,cost_per_unit=1)
def test_no_second_position_same_day():
    trades,skips=replay([s(),Signal(T+timedelta(seconds=30),"NIFTY",Side.CE,"BREAKOUT")],
                        [q(60,99,100),q(120,140,141)])
    assert len(trades)==1 and skips["ONE_POSITION_PER_DAY"]==1
