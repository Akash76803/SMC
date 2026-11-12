from datetime import datetime,timedelta,timezone
import pytest
from smc.models import Candle,Pivot
from smc.structure_v2 import StructuralBreak
from smc.liquidity import LiquidityLevel
from smc.advanced import (find_order_blocks,refine_order_block,find_idm,
                          qualify_atr,select_liquidity_target)
from smc.mtf import aligned_bias,confirm_ltf_direction

T=datetime(2026,11,12,9,15,tzinfo=timezone.utc)

def c(i,op,hi,lo,cl,step=1):
    return Candle(T+timedelta(minutes=i*step),op,hi,lo,cl)

def br(i,d,p=None,tier="INTERNAL"):
    return StructuralBreak("BOS",d,tier,p or Pivot("HIGH",0,110,1),i,None)

def test_ob_last_opposite_pre_break():
    candles=[c(0,101,105,99,104),c(1,105,106,100,101),
             c(2,102,114,101,113)]
    ob=find_order_blocks(candles,[br(2,"BULLISH")])
    assert len(ob)==1 and ob[0].source_index==1
    assert (ob[0].lower,ob[0].upper)==(100,106)

def test_ob_not_found_on_same_candle_or_incomplete():
    candles=[c(0,105,107,100,101),c(1,101,115,101,114)]
    assert find_order_blocks(candles,[br(0,"BULLISH")])==[]
    with pytest.raises(ValueError):
        find_order_blocks(candles,[br(1,"BULLISH")],lookback=0)

def test_refinement_uses_only_parent_window():
    htf=[c(0,105,110,95,100,step=5),c(1,100,115,97,113,step=5)]
    block=find_order_blocks(htf,[br(1,"BULLISH")])[0]
    ltf=[c(0,104,107,101,102),c(1,103,108,99,100),
         c(2,104,106,101,102),c(5,104,105,102,103)]
    refined=refine_order_block(block,htf,ltf)
    assert refined.refined and (refined.lower,refined.upper)==(101,106)

def test_idm_preconfirmed_only():
    pivots=[Pivot("LOW",2,98,4),Pivot("LOW",6,99,8)]
    breaks=[br(9,"BULLISH",Pivot("HIGH",7,110,8))]
    x=find_idm(pivots,breaks)
    assert len(x)==1 and x[0].source_index==2

def test_atr_missing_and_ratio():
    assert not qualify_atr(None,100).accepted
    assert qualify_atr(30,100).accepted
    assert not qualify_atr(10,100).accepted

def test_target_nearest_opposing_and_no_fabrication():
    levels=[LiquidityLevel("BSL",10100,0,(0,),1),
            LiquidityLevel("PDH",10200,0,(0,),1),
            LiquidityLevel("SSL",9900,0,(0,),1)]
    assert select_liquidity_target(10000,"BULLISH",levels,2)==10100
    assert select_liquidity_target(10000,"BEARISH",levels,2)==9900
    assert select_liquidity_target(10300,"BULLISH",levels,2) is None
    assert select_liquidity_target(10000,"BULLISH",levels,2,
                                   invalidated={("BSL",10100)})==10200

def test_htf_not_visible_until_close():
    htf=[c(0,100,110,95,105,step=60),c(1,105,115,100,113,step=60)]
    events=[br(0,"BULLISH",tier="EXTERNAL")]
    assert aligned_bias(c(30,100,102,99,101),htf,events,duration_minutes=60) is None
    assert confirm_ltf_direction("BULLISH",c(60,100,102,99,101),
                                 htf,events,duration_minutes=60)
    assert not confirm_ltf_direction("BEARISH",c(60,100,102,99,101),
                                     htf,events,duration_minutes=60)
