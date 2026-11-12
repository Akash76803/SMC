from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from smc.engine import confirmed_pivots
from smc.liquidity import (LiquidityLevel, classify_liquidity_events,
                           equal_levels, liquidity_map, previous_day_levels,
                           swing_liquidity)
from smc.models import Candle, Pivot
from smc.phase2 import scan
from smc.structure_v2 import detect_structure


START = datetime(2026, 11, 12, 9, 15, tzinfo=ZoneInfo("Asia/Kolkata"))


def make(highs, lows=None, closes=None):
    lows = lows or [h-2 for h in highs]
    closes = closes or [(h+l)/2 for h,l in zip(highs,lows)]
    return [Candle(START + timedelta(minutes=i), c, h, l, c)
            for i,(h,l,c) in enumerate(zip(highs,lows,closes))]


def test_swing_level_not_eligible_until_confirmation():
    cs = make([100,102,110,103,102,111,101])
    p = confirmed_pivots(cs, k=2)
    level = next(l for l in swing_liquidity(p) if l.kind == "BSL")
    assert level.created_at == 4
    assert level.eligible_from == 5


def test_sweep_and_run_differ_by_close():
    cs = make([100,112,114], [98,98,98], [99,105,113])
    lev = LiquidityLevel("BSL",110,0,(0,),1)
    events = classify_liquidity_events(cs,[lev])
    assert len(events)==1
    assert events[0].kind=="SWEEP"
    assert events[0].candle_index==1
    cs2 = make([100,112], [98,100], [99,111])
    assert classify_liquidity_events(cs2,[lev])[0].kind=="RUN"


def test_new_level_not_swept_by_its_own_candle():
    cs = make([100,120], [98,100], [99,110])
    lev = LiquidityLevel("PDH",110,1,(0,),1)
    assert classify_liquidity_events(cs,[lev])==[]


def test_equal_high_pair_is_confirmed_before_level_is_active():
    pivots=[Pivot("HIGH",2,110,4),Pivot("HIGH",7,111,9)]
    zones=equal_levels(pivots,2)
    assert len(zones)==1
    assert zones[0].kind=="EQH"
    assert zones[0].source_indices==(2,7)
    assert zones[0].eligible_from==10


def test_previous_day_uses_ist_date_not_utc():
    a = Candle(datetime(2026,11,11,15,0,tzinfo=ZoneInfo("Asia/Kolkata")),
               100,105,95,101)
    b = Candle(datetime(2026,11,12,9,15,tzinfo=ZoneInfo("Asia/Kolkata")),
               102,104,99,103)
    p=previous_day_levels([a,b])
    assert {(x.kind,x.price) for x in p}=={("PDH",105),("PDL",95)}
    assert all(x.eligible_from==1 for x in p)


def test_incomplete_bar_does_not_create_sweep():
    cs=make([100,115],[98,99],[99,105])
    last=cs[-1]
    cs[-1]=Candle(last.timestamp,last.open,last.high,last.low,last.close,complete=False)
    lev=LiquidityLevel("BSL",110,0,(0,),1)
    assert classify_liquidity_events(cs,[lev])==[]


def test_no_future_pivots_in_replay():
    cs=make([100,102,110,103,102,111,101,100,104,108,112,104])
    earlier=scan(cs[:7])
    later=scan(cs)
    assert all(x.created_at < 7 for x in earlier.levels)
    assert all(x.candle_index < 7 for x in earlier.liquidity_events)
    assert set(earlier.liquidity_events).issubset(set(later.liquidity_events))


def test_structure_parameters_and_replay():
    cs=make([100,103,110,102,100,113,111,106,115,110,105,116],
            [98,99,104,97,96,107,105,100,108,103,98,109],
            [99,102,108,100,98,112,108,104,114,108,102,115])
    with pytest.raises(ValueError):
        detect_structure(cs,internal_k=3,external_k=2)
    events=detect_structure(cs, internal_k=1, external_k=2)
    assert all(cs[x.candle_index].complete for x in events)
    assert all(x.broken_pivot.confirmed_at < x.candle_index for x in events)
    assert all(x.tier in ("INTERNAL","EXTERNAL") for x in events)


def test_scan_is_research_only_not_trade_signal():
    cs=make([100]*18)
    result=scan(cs)
    assert result.status=="RESEARCH_ONLY_NO_TRADE"
    assert result.atr14 is not None
