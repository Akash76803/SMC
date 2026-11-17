"""Event-scoped ICT setup lifecycle: no repainting, no future-data entry.

Each closed-candle structure shift creates an independently tracked research
setup. A shift never becomes a trade by itself; FVG / mitigation are allowed
to occur later. State changes are evaluated only up to `as_of`.

Premium/Discount filter (Gwaidier SMC Lecture #11):
  - BULLISH setups: OB mid-point must be in DISCOUNT zone (below equilibrium)
  - BEARISH setups: OB mid-point must be in PREMIUM zone (above equilibrium)
  - If dealing_range is None, filter is skipped (backward compatible).
"""
from __future__ import annotations
from datetime import datetime
from math import isfinite
from .engine import confirmed_pivots, fair_value_gaps, atr
from .advanced import find_order_blocks
from .liquidity import liquidity_map
from .models import Candle, Zone
from .structure_v2 import detect_structure
from .structure_v3 import structure_hierarchy


def _ob_zone_label(ob_lower: float, ob_upper: float,
                   equilibrium: float) -> str:
    """Return PREMIUM / DISCOUNT / EQUILIBRIUM for an OB based on its midpoint."""
    mid = (ob_lower + ob_upper) / 2.0
    if mid > equilibrium:
        return "PREMIUM"
    if mid < equilibrium:
        return "DISCOUNT"
    return "EQUILIBRIUM"


def _zone_aligned(direction: str, zone_label: str) -> bool:
    """BULLISH OB should sit in DISCOUNT; BEARISH OB should sit in PREMIUM."""
    if direction == "BULLISH":
        return zone_label == "DISCOUNT"
    return zone_label == "PREMIUM"


def find_volume_imbalances(candles: list[Candle]) -> list[Zone]:
    """Adjacent non-overlapping bodies with overlapping wicks (price proxy).

    Unlike a three-candle FVG, these gaps have wick trading but no body
    overlap. This does not assert observed volume on cash indices.
    """
    zones = []
    for i in range(1, len(candles)):
        previous, current = candles[i-1:i+1]
        if not previous.complete or not current.complete:
            continue
        if previous.timestamp >= current.timestamp:
            raise ValueError("UNORDERED_IMBALANCE_INPUT")
        if previous.timestamp.date() != current.timestamp.date():
            continue
        a_low, a_high = sorted((previous.open, previous.close))
        b_low, b_high = sorted((current.open, current.close))
        if a_high < b_low and current.low <= previous.high:
            zones.append(Zone("BULLISH_VOLUME_IMBALANCE", a_high, b_low, i))
        elif b_high < a_low and previous.low <= current.high:
            zones.append(Zone("BEARISH_VOLUME_IMBALANCE", b_high, a_low, i))
    return zones


def classify_poi(*, block=None, idm=None, sweep=None, shift=None, origin=None) -> str:
    """Deterministic research POI taxonomy; middle blocks never qualify.

    Adjacency means the IDM candle or its immediate neighbour; the extreme
    block sits at the latest confirmed opposite swing / CHoCH origin.
    Sweeps cannot legitimise an intermediate OB. No price-only inference
    is treated as evidence of institutional orders.
    """
    block_category = None
    if block is not None:
        if origin is not None and abs(block.source_index-origin.index) <= 1:
            block_category = "EXTREME_OB"
        elif idm is not None and abs(block.source_index-idm.index) <= 1:
            block_category = "DECISIONAL_OB"
        else:
            return "TRAP_MIDDLE_OB"
    if sweep is not None and shift is not None:
        if shift.kind == "CHoCH":
            return "CHOCH_SWEEP"
        if shift.tier == "EXTERNAL":
            return "BOS_SWEEP"
    if block_category is not None:
        return block_category
    return "IDM_SWEEP" if sweep is not None and idm is not None else "UNVERIFIED"


def _context_at(dealing_range, at):
    if dealing_range is None:
        return None
    if "history" in dealing_range:
        known = [context for context in dealing_range['history']
                 if datetime.fromisoformat(context['available_at']) <= at]
        return max(known, key=lambda c: datetime.fromisoformat(c['available_at']), default=None)
    return dealing_range


def scan_ict_lifecycles(candles: list[Candle], *,
                        as_of: int | None = None,
                        max_sweep_lag: int = 35,
                        max_retest_bars: int = 20,
                        min_displacement_atr: float = 0.5,
                        dealing_range: dict | None = None,
                        allow_counter: bool = False) -> list[dict]:
    """Scan ICT lifecycles with optional Premium/Discount OB zone filter.

    Args:
        dealing_range: Optional dict with keys ``equilibrium`` (float) and
            ``position`` (str).  When supplied, each setup whose OB mid-point
            sits on the *wrong* side of equilibrium is tagged
            ``REJECTED_WRONG_ZONE`` and skipped from WAITING_FOR_RETEST
            onwards unless ``allow_counter=True``. Pass None to disable the
            zone filter. Upgraded POI/imbalance rules are opt-in with this
            flag, leaving legacy replay/state semantics unchanged.
    """
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
    hierarchy=structure_hierarchy(bars) if len(bars)>=3 else ()
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
    imbalances=find_volume_imbalances(bars) if allow_counter else []
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
        # Structural swing reference from structure_v3 (Gwaidier Lecture 11: ITH/ITL)
        target_it = "ITL" if bullish else "ITH"
        matching_it = [p for p in hierarchy if p.kind == target_it and p.confirmed_at <= si]
        it_ref = max(matching_it, key=lambda p: p.confirmed_at, default=None)
        target_st = "STL" if bullish else "STH"
        matching_st = [p for p in hierarchy if p.kind == target_st and p.confirmed_at <= si]
        st_ref = max(matching_st, key=lambda p: p.confirmed_at, default=None)
        origins = [p for p in pivots if p.kind == opposite and p.confirmed_at <= si]
        origin = max(origins, key=lambda p: p.confirmed_at, default=None)
        poi = classify_poi(block=block, idm=idm, sweep=sweep, shift=shift, origin=origin)
        vi_kind = "BULLISH_VOLUME_IMBALANCE" if bullish else "BEARISH_VOLUME_IMBALANCE"
        imbalance = next((z for z in imbalances if z.kind == vi_kind
                          and si <= z.created_at <= min(as_of, si+3)), None)
        context = _context_at(dealing_range, bars[si].timestamp)
        if allow_counter and context is not None:
            values = [context.get(key) for key in ('low', 'equilibrium', 'high')]
            if (not all(isinstance(value, (int, float)) and isfinite(value) and value > 0 for value in values)
                or not values[0] < values[1] < values[2]):
                raise ValueError('INVALID_DEALING_RANGE')
        setup_type = None
        target = None
        target_kind = None
        state="WAITING_FOR_SWEEP"
        retest_i=None
        invalidated_i=None
        ob_zone_label: str | None = None
        zone_aligned: bool | None = None
        if sweep is not None:
            state="WAITING_FOR_IDM" if idm is None else "WAITING_FOR_DISPLACEMENT"
            if idm is not None and displacement:
                state="WAITING_FOR_OB" if block is None else "WAITING_FOR_RETEST"
                if block is not None:
                    # --- Premium/Discount filter (Gwaidier Lecture 11) ---
                    if context is not None:
                        eq = context.get("equilibrium")
                        if eq is not None:
                            if not isinstance(eq, (int, float)) or not isfinite(eq) or eq <= 0:
                                raise ValueError("INVALID_DEALING_RANGE")
                            ob_zone_label = _ob_zone_label(block.lower, block.upper, eq)
                            zone_aligned = _zone_aligned(shift.direction, ob_zone_label)
                            setup_type = "PRO_TREND" if zone_aligned else "COUNTER_PULLBACK"
                            target = context.get("high" if bullish else "low") if zone_aligned else eq
                            target_kind = "HTF_EXTERNAL_LIQUIDITY" if zone_aligned else "HTF_EQUILIBRIUM"
                            if not zone_aligned:
                                if not allow_counter:
                                    state = "REJECTED_WRONG_ZONE"
                                elif sweep is None:
                                    state = "WAITING_FOR_SWEEP"
                    if allow_counter and poi == "TRAP_MIDDLE_OB":
                        state = "TRAP_IGNORED"
                    if allow_counter and fvg is None and imbalance is None and state == "WAITING_FOR_RETEST":
                        state = "WAITING_FOR_IMBALANCE"
                    if state == "WAITING_FOR_RETEST":
                        gap = fvg or imbalance
                        begin=max(si,gap.created_at if gap else si)+1
                        deadline=min(as_of+1,begin+max_retest_bars)
                        for i in range(begin,deadline):
                            c=bars[i]
                            if (c.close<block.lower if bullish else c.close>block.upper):
                                state="INVALIDATED"
                                invalidated_i=i
                                break
                            touched=c.low<=block.upper and c.high>=block.lower
                            rejected=c.close>block.upper if bullish else c.close<block.lower
                            if allow_counter and gap is not None:
                                gap_touch = c.low <= gap.upper and c.high >= gap.lower
                                gap_reject = c.close > gap.upper if bullish else c.close < gap.lower
                                if gap_touch and gap_reject:
                                    touched = rejected = True
                            if touched and rejected:
                                if allow_counter and setup_type == "COUNTER_PULLBACK":
                                    # Internal opposing imbalances cap the equilibrium target.
                                    internal = [z.lower if bullish else z.upper for z in fvgs+imbalances
                                                if z.created_at < i and
                                                z.kind.startswith("BEARISH" if bullish else "BULLISH")]
                                    internal.extend(b.lower if bullish else b.upper for b in obs
                                                    if b.structure_index < i and b.direction != shift.direction)
                                    valid = [price for price in internal if
                                             (c.close < price <= target if bullish else target <= price < c.close)]
                                    if valid:
                                        target = min(valid) if bullish else max(valid)
                                        target_kind = "INTERNAL_POI"
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
            "confluence_model": "GWAIDIER_V1" if allow_counter else "LEGACY",
            "setup_type":setup_type,
            "poi_category":poi,
            "poi_valid":poi not in ("UNVERIFIED", "TRAP_MIDDLE_OB"),
            "htf_context":context,
            "target_reference":target,
            "target_kind":target_kind,
            "target_rr_min":3.0 if setup_type == "PRO_TREND" else 2.0,
            "target_is_directional": bool(target is not None and
                (target > bars[retest_i if retest_i is not None else si].close if bullish else
                 target < bars[retest_i if retest_i is not None else si].close)),
            "sweep_at":bars[sweep.candle_index].timestamp.isoformat() if sweep else None,
            "sweep_level":sweep.level.price if sweep else None,
            "idm_at":bars[idm.confirmed_at].timestamp.isoformat() if idm else None,
            "idm_level":idm.price if idm else None,
            "displacement_confirmed":displacement,
            "ob_zone":[block.lower,block.upper] if block else None,
            "fvg_zone":[fvg.lower,fvg.upper] if fvg else None,
            "volume_imbalance_zone":[imbalance.lower,imbalance.upper] if imbalance else None,
            "retest_at":bars[retest_i].timestamp.isoformat() if retest_i is not None else None,
            "invalidated_at":bars[invalidated_i].timestamp.isoformat()
                              if invalidated_i is not None else None,
            "ob_zone_label":ob_zone_label,
            "zone_filter_applied":dealing_range is not None,
            "zone_aligned":zone_aligned,
            "ith_itl_reference": {
                "kind": it_ref.kind,
                "price": it_ref.pivot.price,
                "index": it_ref.pivot.index,
                "confirmed_at": bars[it_ref.confirmed_at].timestamp.isoformat(),
            } if it_ref is not None else None,
            "structural_swing_reference": {
                "kind": (it_ref or st_ref).kind,
                "price": (it_ref or st_ref).pivot.price,
                "index": (it_ref or st_ref).pivot.index,
                "confirmed_at": bars[(it_ref or st_ref).confirmed_at].timestamp.isoformat(),
            } if (it_ref or st_ref) is not None else None,
            "research_only":True,"order_allowed":False,
            "orders_enabled":False,
            "stop_protected_verified":False,
        })
    return rows
