"""Phase 3.3 integrated *research-only* decision pipeline.

Inputs are causally timestamped, caller-supplied candle histories/market quotes.
No live broker calls, real order routing, or automatic recommendation.
The result only means a setup passed *the implemented screening heuristics*.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from .advanced import (OrderBlock, IDM, qualify_atr,
                       select_liquidity_target)
from .engine import atr
from .entry_v1 import State, EntryResult, evaluate_entry
from .liquidity import LiquidityEvent, LiquidityLevel
from .models import Candle, IndexSetup, OptionQuote, Side, Zone
from .mtf import aligned_bias
from .options import rank_options, RankedOption
from .risk import MIN_POINTS
from .structure_v2 import StructuralBreak


class Decision(str, Enum):
    NO_TRADE = "NO_TRADE"
    WAIT = "WAIT"
    RESEARCH_CANDIDATE = "RESEARCH_CANDIDATE"


@dataclass(frozen=True)
class PipelineResult:
    decision: Decision
    reasons: tuple[str, ...]
    entry: EntryResult | None
    option: RankedOption | None
    htf_bias: str | None
    target: float | None
    atr14: float | None


def scan_setup(
    *,
    symbol: str,
    ltf_candles: list[Candle],
    htf_candles: list[Candle],
    htf_events: list[StructuralBreak],
    ltf_events: list[StructuralBreak],
    liquidity_events: list[LiquidityEvent],
    liquidity_levels: list[LiquidityLevel],
    order_blocks: list[OrderBlock],
    idm_candidates: list[IDM],
    option_quotes: list[OptionQuote],
    spot: float,
    now: datetime,
    htf_duration_minutes: int,
    fvg_zones: list[Zone] | None = None,
    max_target_atr: float = 4.0,
    max_candle_age_seconds: int = 300,
    # This is a strict "current candle" scanner, not a historical fill simulator.
) -> PipelineResult:
    if now.tzinfo is None:
        raise ValueError("now must have timezone")
    if symbol not in MIN_POINTS:
        return PipelineResult(Decision.NO_TRADE, ("UNSUPPORTED_SYMBOL",), None,None,None,None,None)
    if htf_duration_minutes<=0 or max_candle_age_seconds<=0 or max_target_atr<=0:
        raise ValueError("invalid pipeline parameters")
    if not ltf_candles or not htf_candles:
        return PipelineResult(Decision.NO_TRADE,("MISSING_CANDLES",),None,None,None,None,None)
    if any(ltf_candles[i].timestamp>=ltf_candles[i+1].timestamp
           for i in range(len(ltf_candles)-1)):
        raise ValueError("LTF candles must be sorted")
    if any(htf_candles[i].timestamp>=htf_candles[i+1].timestamp
           for i in range(len(htf_candles)-1)):
        raise ValueError("HTF candles must be sorted")
    latest_index=len(ltf_candles)-1
    last=ltf_candles[-1]
    # The data adapter must provide CLOSE-TIME timestamps for LTF bars here.
    age=(now-last.timestamp).total_seconds()
    if not last.complete or age<0 or age>max_candle_age_seconds:
        return PipelineResult(Decision.NO_TRADE,("STALE_OR_OPEN_LTF_CANDLE",),
                              None,None,None,None,None)
    current_atr=atr(ltf_candles)
    if current_atr is None:
        return PipelineResult(Decision.NO_TRADE,("ATR_UNAVAILABLE",),
                              None,None,None,None,None)

    # Candidate discovery is strictly historical. No explicit target yet:
    # first determine an entry bar, then choose only targets known at that bar.
    matches=evaluate_entry(ltf_candles,liquidity_events,ltf_events,
                           symbol=symbol,target=None,fvgs=fvg_zones)
    if not matches:
        return PipelineResult(Decision.WAIT,("NO_LIQUIDITY_SWEEP_SETUP",),
                              None,None,None,None,current_atr)
    # Prefer the most recently transitioned setup.
    probe=max(matches,key=lambda r:(r.transition_index,r.sweep_index))
    if probe.state in (State.WAITING_CHOCH, State.WAITING_FVG, State.WAITING_RETEST):
        return PipelineResult(Decision.WAIT,(probe.reason,),probe,None,None,None,current_atr)
    if probe.entry is None or probe.stop is None:
        return PipelineResult(Decision.NO_TRADE,(probe.reason,),probe,None,None,None,current_atr)
    if probe.transition_index!=latest_index:
        return PipelineResult(Decision.NO_TRADE,("HISTORICAL_SIGNAL_NOT_CURRENT",),
                              probe,None,None,None,current_atr)
    direction="BULLISH" if probe.side==Side.CE else "BEARISH"
    bias=aligned_bias(last,htf_candles,htf_events,
                      duration_minutes=htf_duration_minutes)
    if bias!=direction:
        return PipelineResult(Decision.NO_TRADE,("HTF_BIAS_MISMATCH_OR_MISSING",),
                              probe,None,bias,None,current_atr)
    if probe.choch_index is None:
        return PipelineResult(Decision.NO_TRADE,("MISSING_CONFIRMED_CHOCH",),
                              probe,None,bias,None,current_atr)

    # Provisional OB/IDM origin rules; confirmation happened before entry.
    suitable_obs=[o for o in order_blocks if
                  o.direction==direction and o.confirmed_at<=probe.transition_index
                  and o.source_index<probe.choch_index
                  and o.structure_index>=probe.choch_index]
    if not suitable_obs:
        return PipelineResult(Decision.NO_TRADE,("MISSING_OB_CONTEXT",),
                              probe,None,bias,None,current_atr)
    suitable_idm=[d for d in idm_candidates if d.direction==direction
                  and d.confirmed_at<=probe.transition_index
                  and d.source_index<probe.choch_index]
    if not suitable_idm:
        return PipelineResult(Decision.NO_TRADE,("MISSING_IDM_PROXY",),
                              probe,None,bias,None,current_atr)

    # A consumed liquidity pool cannot be the target. Do not look into the future.
    consumed={(e.level.kind,e.level.price) for e in liquidity_events
              if e.candle_index<=probe.transition_index}
    target=select_liquidity_target(
        probe.entry,direction,liquidity_levels,probe.transition_index,
        invalidated=consumed)
    if target is None:
        return PipelineResult(Decision.NO_TRADE,("NO_UNCONSUMED_LIQUIDITY_TARGET",),
                              probe,None,bias,None,current_atr)
    points=abs(target-probe.entry)
    vol=qualify_atr(current_atr,points,max_target_atr=max_target_atr)
    if not vol.accepted:
        return PipelineResult(Decision.NO_TRADE,(vol.reason,),probe,None,bias,target,current_atr)

    # Re-evaluate one sweep (never reclassify a different setup) against target.
    corresponding=[e for e in liquidity_events if e.kind=="SWEEP"
                   and e.candle_index==probe.sweep_index
                   and (("BSL" if probe.side==Side.PE else "SSL") in
                        (("BSL" if e.level.kind in ("BSL","EQH","PDH") else "SSL"),))]
    if not corresponding:
        return PipelineResult(Decision.NO_TRADE,("MISSING_SOURCE_SWEEP",),
                              probe,None,bias,target,current_atr)
    verified=evaluate_entry(
        ltf_candles,[corresponding[0]],ltf_events,symbol=symbol,
        target=target,fvgs=fvg_zones)
    final=verified[0] if verified else probe
    if final.state!=State.CANDIDATE:
        return PipelineResult(Decision.NO_TRADE,(final.reason,),final,None,bias,target,current_atr)

    # Index RR is necessary but option RR and delta are mandatory too.
    setup=IndexSetup(symbol,final.side,final.entry,final.stop,target,
                     True,scheme="RESEARCH_LIQUIDITY_V1")
    ranked=rank_options(setup,spot,option_quotes,now)
    if not ranked:
        return PipelineResult(Decision.NO_TRADE,
                              ("NO_ELIGIBLE_OPTION_DELTA_LIQUIDITY_OR_NET_RR",),
                              final,None,bias,target,current_atr)
    return PipelineResult(Decision.RESEARCH_CANDIDATE,
                          ("RESEARCH_ONLY_NOT_LIVE_TRADE_APPROVAL",),
                          final,ranked[0],bias,target,current_atr)
