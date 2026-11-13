from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from smc.models import Candle,Side
from smc.phase6_ohlc import OptionSeries,IndexEvent,simulate
IST=ZoneInfo("Asia/Kolkata")
START=datetime(2026,11,11,10,50,tzinfo=IST)
def test_same_direction_strategy_votes_do_not_double_count_pnl():
    bars=(Candle(START+timedelta(minutes=1),100,110,99,105),
          Candle(START+timedelta(minutes=2),105,130,104,125))
    events=(IndexEvent(START,"NIFTY",Side.CE,"BOS_FVG_CONTINUATION"),
            IndexEvent(START,"NIFTY",Side.CE,"PIVOT_BREAKOUT_RETEST"))
    trades,diagnostics=simulate(events,OptionSeries(
        "NIFTY17NOV2625350CE","45404","17NOV2026",bars))
    assert len(trades)==1
    assert trades[0].gross_premium_points==25
    assert trades[0].strategy=="BOS_FVG_CONTINUATION+PIVOT_BREAKOUT_RETEST"
    assert diagnostics["DUPLICATE_STRATEGY_LABELS_COLLAPSED"]==1

def test_different_time_is_distinct_opportunity():
    bars=(Candle(START+timedelta(minutes=1),100,130,99,125),
          Candle(START+timedelta(minutes=2),100,130,99,125))
    signals=(IndexEvent(START,"NIFTY",Side.CE,"BOS"),
             IndexEvent(START+timedelta(minutes=1),"NIFTY",Side.CE,"BREAKOUT"))
    trades,_=simulate(signals,OptionSeries("NIFTY17NOV2625350CE","45404","",bars))
    assert len(trades)==2
