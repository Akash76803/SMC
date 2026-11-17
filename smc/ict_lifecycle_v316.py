"""Event-scoped ICT setup lifecycle: no repainting, no future-data entry.

Each closed-candle structure shift creates an independently tracked research
setup. A shift never becomes a trade by itself; FVG / mitigation are allowed
to occur later. State changes are evaluated only up to `as_of`.
"""
from __future__ import annotations
from .engine import confirmed_pivots, fair_value_gaps, atr
from .advanced import find_order_blocks
from .liquidity import liquidity_map
from .models import Candle
from .structure_v2 import detect_structure


def scan_ict_lifecycles(candles: list[Candle], *,
                        as_of: int | None = None,
                        max_sweep_lag: int = 35,
                        max_retest_bars: int = 20,
                        min_displacement_atr: float = 0.5) -> list[dict]:
    if not candles:
        raise ValueError("EMPTY_LIFECYCLE_INPUT")
    if as_of is None:
        as_of = len(candles)-1
    if not 0 <= as_of < len(candles):
        raise ValueError("INVALID_LIFECYCLE_AS_OF")
    if max_sweep_lag < 1 or max_retest_bars < 1 or min_displacement_atr <= 0:
        raise ValueError("INVALID_LIFECYCLE_CONFIG")
    bars=candles[:as_of+1]
    if any(not b.complete for b in bars):
        raise ValueError("INCOMPLETE_LIFECYCLE_INPUT")
    if any(a.timestamp>=b.timestamp for a,b in zip(bars,bars[1:])):
        raise ValueError("UNORDERED_LIFECYCLE_INPUT")
    if len({b.timestamp.date() for b in bars}) != 1:
        raise ValueError("MULTI_SESSION_LIFECYCLE_INPUT")

    pivots=confirmed_pivots(bars,k=2)
    all_b=detect_structure(bars,internal_k=2,external_k=5)
    seen={}
    for b in all_b:
        key=(b.candle_index,b.direction)
        if key not in seen or b.tier=="EXTERNAL":
            seen[key]=b
    breaks=sorted(seen.values(),key=lambda b:b.candle_index)
    _,liquidity=liquidity_map(bars,pivots)
    obs=find_order_blocks(bars,breaks)
    fvgs=fair_value_gaps(bars)
    rows=[]
    for shift in breaks:
        si=shift.candle_index
        bullish=shift.direction=="BULLISH"
        source_types={"SSL","EQL"} if bullish else {"BSL","EQH"}
        sweeps=[e for e in liquidity if e.kind=="SWEEP"
                and e.level.kind in source_types
                and 0<si-e.candle_index<=max_sweep_lag]
        sweep=max(sweeps,key=lambda e:e.candle_index,default=None)
        opposite="LOW" if bullish else "HIGH"
        # Candidate IDM must be confirmed strictly before sweep.
        matching_idm=[p for p in pivots if sweep is not None
                      and p.kind==opposite and p.confirmed_at<sweep.candle_index
                      and (sweep.level.price<=p.price if bullish
                           else sweep.level.price>=p.price)]
        idm=max(matching_idm,key=lambda p:p.confirmed_at,default=None)
        historical_atr=atr(bars[:si],14) if si>=15 else None
        shift_c=bars[si]
        displacement=bool(historical_atr and
            (shift_c.close>shift_c.open if bullish else shift_c.close<shift_c.open)
            and abs(shift_c.close-shift_c.open)>=historical_atr*min_displacement_atr)
        block=next((b for b in obs if b.structure_index==si
                    and b.direction==shift.direction),None)
        fvg_kind="BULLISH_FVG" if bullish else "BEARISH_FVG"
        fvg=next((z for z in fvgs if z.kind==fvg_kind
                  and si<=z.created_at<=min(as_of,si+3)),None)
        state="WAITING_FOR_SWEEP"
        retest_i=None
        invalidated_i=None
        if sweep is not None:
            state="WAITING_FOR_IDM" if idm is None else "WAITING_FOR_DISPLACEMENT"
            if idm is not None and displacement:
                state="WAITING_FOR_OB" if block is None else "WAITING_FOR_RETEST"
                if block is not None:
                    begin=max(si,fvg.created_at if fvg else si)+1
                    deadline=min(as_of+1,begin+max_retest_bars)
                    for i in range(begin,deadline):
                        c=bars[i]
                        if (c.close<block.lower if bullish else c.close>block.upper):
                            state="INVALIDATED"
                            invalidated_i=i
                            break
                        touched=c.low<=block.upper and c.high>=block.lower
                        rejected=c.close>block.upper if bullish else c.close<block.lower
                        if touched and rejected:
                            state="RETEST_CONFIRMED_RESEARCH"
                            retest_i=i
                            break
                    if state=="WAITING_FOR_RETEST" and as_of>=begin+max_retest_bars-1:
                        state="EXPIRED"
        rows.append({
            "setup_id": f"{bars[si].timestamp.isoformat()}:{shift.direction}",
            "shift_at":bars[si].timestamp.isoformat(),
            "direction":shift.direction,
            "structure_kind":shift.kind,
            "state":state,
            "sweep_at":bars[sweep.candle_index].timestamp.isoformat() if sweep else None,
            "sweep_level":sweep.level.price if sweep else None,
            "idm_at":bars[idm.confirmed_at].timestamp.isoformat() if idm else None,
            "idm_level":idm.price if idm else None,
            "displacement_confirmed":displacement,
            "ob_zone":[block.lower,block.upper] if block else None,
            "fvg_zone":[fvg.lower,fvg.upper] if fvg else None,
            "retest_at":bars[retest_i].timestamp.isoformat() if retest_i is not None else None,
            "invalidated_at":bars[invalidated_i].timestamp.isoformat()
                              if invalidated_i is not None else None,
            "research_only":True,"order_allowed":False,
            "stop_protected_verified":False,
        })
    return rows
