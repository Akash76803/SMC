"""Conservative causal INDEX bracket for an independently observed SMC retest.

No live order eligibility. Bracket uses last closed-candle price, not a
hypothetical next-bar open. It MUST be repriced at the next executable
tick/open; real options premium is wholly separate.
"""
from __future__ import annotations
from .engine import confirmed_pivots, atr
from .liquidity import liquidity_map
from .models import Candle, IndexSetup, Side
from .risk import validate_index_setup


def research_bracket(*, symbol: str, candles: list[Candle], lifecycle: dict) -> dict:
    empty={"status":"NO_VERIFIED_INDEX_BRACKET","entry_close_reference":None,
           "stop_reference":None,"target_t1":None,"targets":[],
           "index_rr_reference":None,"stop_is_verified_protected":False,
           "entry_is_executable":False,"research_only":True,
           "reason":"NO_CONFIRMED_CURRENT_RETEST",
           "min_target_required":None,"atr14":None}
    if symbol not in ("NIFTY","SENSEX") or not candles:
        return empty
    if lifecycle.get("state")!="RETEST_CONFIRMED_RESEARCH":
        return empty
    at=candles[-1].timestamp.isoformat()
    retest_at=lifecycle.get("retest_at")
    if not retest_at:
        return empty
    retest_idx=next((i for i,b in enumerate(candles) if b.timestamp.isoformat()==retest_at),None)
    if retest_idx is None or (len(candles)-1-retest_idx)>15:
        return {**empty,"reason":"RETEST_NOT_RECENT"}
    direction=lifecycle.get("direction")
    if direction not in ("BULLISH","BEARISH"):
        return {**empty,"reason":"DIRECTION_UNVERIFIED"}
    bullish=direction=="BULLISH"
    sweep_at=lifecycle.get("sweep_at")
    origin=next((b for b in candles if b.timestamp.isoformat()==sweep_at),None)
    zone=lifecycle.get("ob_zone")
    if (origin is None or not isinstance(zone,list) or len(zone)!=2):
        return {**empty,"reason":"SWEEP_OR_OB_UNAVAILABLE"}
    entry=candles[retest_idx].close
    atr_val = atr(candles, length=14)
    atr_buffer = (atr_val or 15.0) * 1.5
    if bullish:
        stop = origin.low if (zone[0] - origin.low) <= atr_buffer else zone[0]
    else:
        stop = origin.high if (origin.high - zone[1]) <= atr_buffer else zone[1]
    if not (stop<entry if bullish else stop>entry):
        return {**empty,"reason":"INVALID_STRUCTURAL_STOP_PROXY"}
    if any((c.close<stop if bullish else c.close>stop) for c in candles[retest_idx:]):
        return {**empty,"reason":"STRUCTURAL_STOP_BREACHED"}
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
    # Dynamic Volatility-Adaptive Target Room
    floor = 30.0 if symbol == "NIFTY" else 60.0
    mult = 2.0
    default_fixed = 50.0 if symbol == "NIFTY" else 100.0
    dyn_min = max(floor, round(mult * atr_val, 1)) if atr_val is not None and atr_val > 0 else default_fixed

    # Nearest first: preferring targets meeting dyn_min room
    targets=[]
    matching=[level for level in candidates if abs(level.price-entry)>=dyn_min]
    pool = matching if matching else candidates
    for level in pool[:3]:
        targets.append({"price":level.price,"kind":level.kind,
                        "strength":level.strength})
    if not targets:
        proj_pts = dyn_min + 1.0
        proj_price = round(entry + proj_pts, 1) if bullish else round(entry - proj_pts, 1)
        targets = [{"price": proj_price, "kind": "PROJECTION_ATR", "strength": 1}]
    first = targets[0]
    test = None
    for tgt in targets:
        curr_test = validate_index_setup(IndexSetup(
            symbol=symbol, side=Side.CE if bullish else Side.PE,
            entry=entry, stop=stop, target=tgt["price"],
            confirmed=True, scheme="SMC_RETEST_REFERENCE"),
            min_target_points=dyn_min)
        if curr_test.accepted:
            first = tgt
            test = curr_test
            break
    if test is None:
        first = targets[0]
        test = validate_index_setup(IndexSetup(
            symbol=symbol, side=Side.CE if bullish else Side.PE,
            entry=entry, stop=stop, target=first["price"],
            confirmed=True, scheme="SMC_RETEST_REFERENCE"),
            min_target_points=dyn_min)
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
        "min_target_required":dyn_min,
        "atr14":round(atr_val,2) if atr_val is not None else None,
    }
