"""Phase 5 experimental multi-setup INDEX research (not option execution).

Two independently defined setups: BOS -> directional FVG retest, and
confirmed pivot breakout -> level retest. Every decision uses closed LTF
candles and HTF bars that closed at or before that decision. Same-session
positions only, strict existing index target / 2R risk gate. No synthetic
liquidity, no guaranteed signals, no option premiums or Greeks.
"""
from __future__ import annotations
from dataclasses import dataclass
from collections import Counter
from datetime import timedelta
from typing import Sequence

from .advanced import select_liquidity_target
from .backtest import Signal
from .engine import fair_value_gaps
from .historical_replay import ReplayConfig
from .models import Candle,IndexSetup,Side
from .phase2 import scan
from .risk import validate_index_setup
from .structure_v2 import detect_structure

CONTINUATION="BOS_FVG_CONTINUATION"
BREAKOUT="PIVOT_BREAKOUT_RETEST"
STRATEGIES=(CONTINUATION,BREAKOUT)

@dataclass(frozen=True)
class SetupDecision:
    strategy:str
    signal:Signal|None
    reason:str
    trigger_index:int|None=None
    side:Side|None=None
    entry:float|None=None
    stop:float|None=None
    target:float|None=None
    rr:float|None=None

def _active_htf_bias(htf:Sequence[Candle], now,config:ReplayConfig)->str|None:
    length=timedelta(minutes=config.htf_duration_minutes)
    eligible=[c for c in htf if c.timestamp+length<=now]
    if len(eligible)<2*config.external_k+2:
        return None
    structure=detect_structure(eligible,internal_k=config.internal_k,
                               external_k=config.external_k)
    external=[e for e in structure if e.tier=="EXTERNAL"]
    return external[-1].direction if external else None

def evaluate_setup(candles:Sequence[Candle],htf:Sequence[Candle],
                   config:ReplayConfig,strategy:str,
                   *,max_retest_bars:int=12)->SetupDecision:
    """Last-bar decision; no historical signal re-emission.

    Each strategy sees only the prefix received by the backtester.
    """
    if strategy not in STRATEGIES:
        raise ValueError("UNKNOWN_STRATEGY")
    if max_retest_bars<1:
        raise ValueError("INVALID_RETEST_WINDOW")
    n=len(candles)
    if n<16:
        return SetupDecision(strategy,None,"LTF_WARMUP")
    if any(not x.complete for x in candles):
        return SetupDecision(strategy,None,"INCOMPLETE_LTF")
    cs=list(candles)
    i=n-1
    bias=_active_htf_bias(htf,cs[-1].timestamp,config)
    if bias is None:
        return SetupDecision(strategy,None,"HTF_BIAS_UNAVAILABLE")
    phase=scan(cs,internal_k=config.internal_k,
               external_k=config.external_k,
               equal_tolerance=config.equal_tolerance)
    internal=[e for e in phase.structure_events
              if e.tier=="INTERNAL" and e.kind=="BOS"
              and e.candle_index<i
              and i-e.candle_index<=max_retest_bars]
    if not internal:
        return SetupDecision(strategy,None,"NO_RECENT_BOS")
    gaps=fair_value_gaps(cs) if strategy==CONTINUATION else []
    # Scan newest first. A previously identified setup cannot be re-emitted:
    # confirmation requires retest on THIS closing candle.
    rejected_reason="NO_CURRENT_RETEST"
    for event in reversed(internal):
        direction=event.direction
        side=Side.CE if direction=="BULLISH" else Side.PE
        trigger=event.candle_index
        level=event.broken_pivot.price
        if strategy==CONTINUATION:
            zones=[z for z in gaps
                   if z.kind==("BULLISH_FVG" if side==Side.CE else "BEARISH_FVG")
                   and trigger<=z.created_at<i]
            if not zones:
                rejected_reason="NO_POST_BOS_FVG"
                continue
            # Latest zone is preferred; retest must occur on current candle.
            zone=max(zones,key=lambda z:z.created_at)
            touched=cs[i].low<=zone.upper and cs[i].high>=zone.lower
            confirmed=cs[i].close>zone.upper if side==Side.CE else cs[i].close<zone.lower
            if not(touched and confirmed):
                continue
            stop=min(cs[j].low for j in range(trigger,i+1)) if side==Side.CE else max(
                cs[j].high for j in range(trigger,i+1))
        else:
            # An old pivot is broken with a *close*, followed by a separate
            # candle that touches its level and confirms on the breakout side.
            touched=cs[i].low<=level<=cs[i].high
            confirmed=cs[i].close>level if side==Side.CE else cs[i].close<level
            if not(touched and confirmed):
                continue
            # Stop beyond the closest locally observed opposing extreme,
            # including the confirmed retest candle. This is a price proxy.
            stop=min(cs[j].low for j in range(max(0,trigger-3),i+1)) if side==Side.CE else max(
                cs[j].high for j in range(max(0,trigger-3),i+1))
        entry=cs[i].close
        if direction!=bias:
            return SetupDecision(strategy,None,"HTF_BIAS_MISMATCH",
                                 trigger,side,entry,stop)
        if not(stop<entry if side==Side.CE else stop>entry):
            return SetupDecision(strategy,None,"INVALID_STOP_GEOMETRY",
                                 trigger,side,entry,stop)
        consumed={(e.level.kind,e.level.price) for e in phase.liquidity_events
                  if e.candle_index<=i}
        target=select_liquidity_target(entry,direction,list(phase.levels),i,
                                       invalidated=consumed)
        if target is None:
            return SetupDecision(strategy,None,"NO_VERIFIED_LIQUIDITY_TARGET",
                                 trigger,side,entry,stop)
        setup=IndexSetup(config.symbol,side,entry,stop,target,True,strategy)
        checked=validate_index_setup(setup)
        if not checked.accepted:
            return SetupDecision(strategy,None,",".join(checked.reasons),
                                 trigger,side,entry,stop,target,checked.index_rr)
        return SetupDecision(strategy,Signal(setup,i),"APPROVED_INDEX_RESEARCH",
                             trigger,side,entry,stop,target,checked.index_rr)
    return SetupDecision(strategy,None,rejected_reason)

class StrategyReplay:
    def __init__(self,config:ReplayConfig,htf:Sequence[Candle],strategy:str):
        if strategy not in STRATEGIES:
            raise ValueError("UNKNOWN_STRATEGY")
        self.config=config
        self.htf=tuple(htf)
        self.strategy=strategy
        self.decisions:list[SetupDecision]=[]
    def __call__(self,prefix:tuple[Candle,...])->Signal|None:
        result=evaluate_setup(prefix,self.htf,self.config,self.strategy)
        self.decisions.append(result)
        return result.signal

def summarize_decisions(decisions:Sequence[SetupDecision])->dict:
    """One decision per evaluated prefix, not a number of distinct setups."""
    return dict(sorted(Counter(d.reason for d in decisions).items()))
