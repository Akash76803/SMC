"""Conservative causal INDEX bracket for an independently observed SMC retest.

No live order eligibility. Bracket uses last closed-candle price, not a
hypothetical next-bar open. It MUST be repriced at the next executable
tick/open; real options premium is wholly separate.
"""
from __future__ import annotations
from .engine import confirmed_pivots
from .liquidity import liquidity_map
from .models import Candle, IndexSetup, Side
from .risk import validate_index_setup


def research_bracket(*, symbol: str, candles: list[Candle], lifecycle: dict) -> dict:
    empty={"status":"NO_VERIFIED_INDEX_BRACKET","entry_close_reference":None,
           "stop_reference":None,"target_t1":None,"targets":[],
           "index_rr_reference":None,"stop_is_verified_protected":False,
           "entry_is_executable":False,"research_only":True,
           "reason":"NO_CONFIRMED_CURRENT_RETEST"}
    if symbol not in ("NIFTY","SENSEX") or not candles:
        return empty
    if lifecycle.get("state")!="RETEST_CONFIRMED_RESEARCH":
        return empty
    at=candles[-1].timestamp.isoformat()
    if lifecycle.get("retest_at")!=at:
        return {**empty,"reason":"RETEST_NOT_ON_LAST_CLOSED_CANDLE"}
    direction=lifecycle.get("direction")
    if direction not in ("BULLISH","BEARISH"):
        return {**empty,"reason":"DIRECTION_UNVERIFIED"}
    bullish=direction=="BULLISH"
    sweep_at=lifecycle.get("sweep_at")
    origin=next((b for b in candles if b.timestamp.isoformat()==sweep_at),None)
    zone=lifecycle.get("ob_zone")
    if (origin is None or not isinstance(zone,list) or len(zone)!=2):
        return {**empty,"reason":"SWEEP_OR_OB_UNAVAILABLE"}
    entry=candles[-1].close
    stop=min(origin.low,zone[0]) if bullish else max(origin.high,zone[1])
    if not (stop<entry if bullish else stop>entry):
        return {**empty,"reason":"INVALID_STRUCTURAL_STOP_PROXY"}
    pivots=confirmed_pivots(candles,k=2)
    levels,events=liquidity_map(candles,pivots)
    # Any touched level is consumed; eligible levels must exist strictly
    # before current candle. Avoid fabricated fixed-index-point targets.
    consumed={(e.level.kind,e.level.price,e.level.source_indices) for e in events
              if e.candle_index<=len(candles)-1}
    desired={"BSL","EQH","PDH"} if bullish else {"SSL","EQL","PDL"}
    candidates=[level for level in levels if
                level.kind in desired
                and level.eligible_from<=len(candles)-1
                and level.created_at<len(candles)-1
                and (level.kind,level.price,level.source_indices) not in consumed
                and (level.price>entry if bullish else level.price<entry)]
    candidates.sort(key=lambda lev:lev.price,reverse=not bullish)
    # Nearest first: no skipping an infeasible T1 to inflate returns.
    targets=[]
    for level in candidates[:3]:
        targets.append({"price":level.price,"kind":level.kind,
                        "strength":level.strength})
    if not targets:
        return {**empty,"entry_close_reference":entry,
                "stop_reference":stop,"reason":"NO_UNCONSUMED_LIQUIDITY_TARGET"}
    first=targets[0]
    test=validate_index_setup(IndexSetup(
        symbol=symbol,side=Side.CE if bullish else Side.PE,
        entry=entry,stop=stop,target=first["price"],
        confirmed=True,scheme="SMC_RETEST_REFERENCE"))
    return {
        "status":"RESEARCH_INDEX_BRACKET_PASSES" if test.accepted
                 else "NO_VERIFIED_INDEX_BRACKET",
        "entry_close_reference":entry,"stop_reference":stop,
        "target_t1":first["price"],"targets":targets,
        "index_rr_reference":test.index_rr,
        "reason":"INDEX_POLICY_PASSED_REFERENCE_NOT_EXECUTABLE"
                 if test.accepted else "|".join(test.reasons),
        "stop_is_verified_protected":False,
        "entry_is_executable":False,"research_only":True,
    }
