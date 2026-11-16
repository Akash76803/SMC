from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from smc.models import Candle, Pivot
from smc.liquidity import LiquidityLevel, LiquidityEvent
from smc.structure_v2 import StructuralBreak
from smc.decision_v3 import CheckState
from smc.poi_liquidity_v3 import (
    review_liquidity_target, review_ob_fvg_poi, index_bracket_from_target,
    candidate_poi_stage,
)

T=datetime(2026,11,16,9,16,tzinfo=ZoneInfo("Asia/Kolkata"))

def candles(values):
    return [Candle(T+timedelta(minutes=i),o,h,l,c)
            for i,(o,h,l,c) in enumerate(values)]

def flat(n=8, price=100):
    return candles([(price, price+1, price-1, price)] * n)

def level(kind="BSL",price=170,created=1,eligible=2):
    return LiquidityLevel(kind,price,created,(0,),eligible)

def target(cs=None,levels=None,events=None,**kwargs):
    cs=flat() if cs is None else cs
    args=dict(candles=cs,levels=[level()] if levels is None else levels,
              events=[] if events is None else events,
              direction="BULLISH",entry=100,stop=80,symbol="NIFTY",
              as_of=cs[-1].timestamp)
    args.update(kwargs)
    return review_liquidity_target(**args)

def test_candidate_selects_nearest_eligible_opposing_pool():
    r=target(levels=[level(price=190),level(price=170)])
    assert r.status=="CANDIDATE" and r.target.price==170
    assert r.target.index_rr==3.5

def test_not_yet_confirmed_level_cannot_be_used():
    assert target(levels=[level(created=7,eligible=8)]).status=="WAIT"

def test_swept_level_is_no_longer_available_even_without_events_list():
    cs=flat()
    x=cs[4]
    cs[4]=Candle(x.timestamp,100,175,99,100)
    assert target(cs=cs).status=="WAIT"

def test_consumed_event_disqualifies_target():
    cs=flat()
    ev=LiquidityEvent("SWEEP",level(),4,"BULLISH",5)
    assert target(cs=cs,events=[ev]).status=="WAIT"

def test_index_target_room_and_rr_are_separate_rejections():
    r=target(levels=[level(price=140)])
    assert r.status=="NO_TRADE" and r.reason=="INDEX_TARGET_TOO_SMALL"
    r=target(levels=[level(price=170)],stop=50)
    assert r.reason=="INDEX_RR_BELOW_MINIMUM"

def test_bearish_opposing_liquidity():
    cs=flat(8,price=200)
    r=review_liquidity_target(
        candles=cs,levels=[level(kind="SSL",price=120)],
        events=[],direction="BEARISH",entry=200,stop=230,
        symbol="NIFTY",as_of=cs[-1].timestamp)
    assert r.status=="CANDIDATE" and r.target.price==120

def test_pdh_first_eligible_bar_consumption():
    cs=flat()
    first=cs[3]
    cs[3]=Candle(first.timestamp,100,180,99,100)
    pdh=LiquidityLevel("PDH",170,3,(1,),3)
    assert target(cs=cs,levels=[pdh]).status=="WAIT"

def test_poi_overlap_detects_candidate_without_claiming_verified_entry():
    cs=candles([
        (95,100,90,96),
        (108,110,96,98),
        (106,115,105,114),
        (112,118,102,116),
        (116,120,112,119),
    ])
    event=StructuralBreak("BOS","BULLISH","INTERNAL",
                          Pivot("HIGH",0,100,1),2,None)
    result=review_ob_fvg_poi(
        candles=cs,breaks=[event],direction="BULLISH",
        as_of=cs[-1].timestamp)
    assert result.status=="CANDIDATE"
    zone=result.zones[0]
    assert (zone.lower,zone.upper)==(100,105)
    assert zone.retest_index==3
    assert candidate_poi_stage(result).state is CheckState.PENDING

def test_no_entry_if_no_verified_target():
    assert index_bracket_from_target(
        entry=100,stop=80,direction="BULLISH",
        review=target(levels=[])) is None

def test_index_bracket_created_for_feasible_target():
    r=target()
    b=index_bracket_from_target(entry=100,stop=80,direction="BULLISH",review=r)
    assert b.target==170 and b.rr==3.5

def test_future_or_incomplete_history_rejected():
    cs=flat()
    with pytest.raises(ValueError,match="FUTURE_CANDLE"):
        target(cs=cs,as_of=cs[2].timestamp)
    cs[1]=Candle(cs[1].timestamp,100,101,99,100,complete=False)
    with pytest.raises(ValueError,match="INCOMPLETE_CANDLE"):
        target(cs=cs)

def test_unordered_rejected():
    cs=flat()
    with pytest.raises(ValueError,match="CANDLES_NOT_STRICTLY_ORDERED"):
        target(cs=[cs[1],cs[0],*cs[2:]])

def test_poi_missing_overlap_stays_wait():
    cs=flat()
    result=review_ob_fvg_poi(candles=cs,breaks=[],direction="BULLISH",as_of=cs[-1].timestamp)
    assert result.status=="WAIT"
    assert candidate_poi_stage(result).state is CheckState.PENDING

def test_poi_candidate_never_automatically_passes_htf_poi():
    cs=candles([
        (100,104,96,98),
        (98,100,94,96),  # origin bearish OB
        (96,109,95,108), # bullish structural break
        (108,110,104,109),
        (109,111,105,110),
        (110,112,109,111),
    ])
    event=StructuralBreak("BOS","BULLISH","INTERNAL",Pivot("HIGH",0,104,1),2,None)
    result=review_ob_fvg_poi(
        candles=cs,breaks=[event],direction="BULLISH",as_of=cs[-1].timestamp)
    assert candidate_poi_stage(result).state is CheckState.PENDING

def test_unknown_direction_and_invalid_event_rejected():
    cs=flat()
    with pytest.raises(ValueError):
        review_ob_fvg_poi(candles=cs,breaks=[],direction="SIDEWAYS",as_of=cs[-1].timestamp)
    e=StructuralBreak("BOS","BULLISH","INTERNAL",Pivot("HIGH",0,105,1),99,None)
    with pytest.raises(ValueError,match="INVALID_STRUCTURE_EVENT_INDEX"):
        review_ob_fvg_poi(candles=cs,breaks=[e],direction="BULLISH",as_of=cs[-1].timestamp)
