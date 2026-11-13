from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from smc.models import Candle,Side
from smc.phase6_ohlc import OptionSeries,IndexEvent,simulate
IST=ZoneInfo("Asia/Kolkata")
START=datetime(2026,11,11,10,1,tzinfo=IST)
def bar(t,o,h,l,c):
    return Candle(START+timedelta(minutes=t),o,h,l,c)
def signal():
    return IndexEvent(START,"NIFTY",Side.CE,"TEST")
def run(bars,**kw):
    return simulate((signal(),),OptionSeries("NIFTY17NOV2625350CE","45404","17NOV2026",tuple(bars)),**kw)
def test_next_bar_open_not_signal_bar_close():
    trades,_=run([bar(0,100,200,10,150),bar(1,110,118,100,114),bar(2,114,145,112,140)])
    assert len(trades)==1
    assert trades[0].entry_open==110
    assert trades[0].exit_reason=="STOP_OHLC"  # next entry candle low touches 100
def test_target_when_no_stop():
    trades,_=run([bar(0,100,101,99,100),bar(1,110,136,107,132)])
    assert trades[0].exit_reason=="TARGET_OHLC"
    assert trades[0].gross_premium_points==25
def test_both_stop_and_target_stop_first():
    trades,_=run([bar(0,100,101,99,100),bar(1,110,180,95,120)])
    assert trades[0].exit_reason=="STOP_OHLC"
    assert trades[0].gross_premium_points==-10
def test_missing_next_bar_never_fills():
    trades,skips=run([bar(0,100,101,99,100),bar(2,112,140,110,134)])
    assert not trades and skips["NO_CONTIGUOUS_NEXT_OPTION_BAR"]==1
def test_missing_midbar_no_fictitious_exit():
    trades,skips=run([bar(0,100,101,99,100),bar(1,110,120,105,115),
                      bar(3,120,160,118,150)])
    assert not trades and skips["INTRATRADE_MISSING_CANDLE"]==1
def test_no_overnight():
    last=datetime(2026,11,11,15,15,tzinfo=IST)
    e=IndexEvent(last,"NIFTY",Side.CE,"TEST")
    trades,skips=simulate((e,),OptionSeries("NIFTY17NOV2625350CE","45404",
                                      "17NOV2026",(bar(0,100,101,99,100),)))
    assert not trades and skips["LATE_SIGNAL"]==1
def test_pe_signal_requires_pe_contract():
    trades,skips=run([bar(0,100,101,99,100)],hold_bars=1)
    assert not trades
    pe=IndexEvent(START,"NIFTY",Side.PE,"TEST")
    trades,skips=simulate((pe,),OptionSeries("NIFTY17NOV2625350CE","45404","",()))
    assert skips["SIGNAL_CONTRACT_MISMATCH"]==1
