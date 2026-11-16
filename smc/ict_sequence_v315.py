"""V3.15 ICT/SMC candle-sequence *research* validator.

Engineering definitions, not proof of institutional orders:
- IDM: pre-break opposing confirmed local swing (provisional inducement).
- Sweep: wick across a confirmed local liquidity pool, close back inside.
- Shift: close-based INTERNAL BOS/CHoCH in intended direction.
- Displacement: directional break-body / true-range test against past ATR.
- Mitigation: first post-confirmation visit to a prior opposite-body OB,
  optionally confluenced with an already formed three-candle FVG.

Evidence must be known by `as_of`. A missing stage means WAIT, never a BUY
or SELL signal. No forward bars are used to qualify historical observations.
"""
from __future__ import annotations

from collections import Counter

from .advanced import find_idm, find_order_blocks
from .engine import atr, confirmed_pivots, fair_value_gaps
from .liquidity import liquidity_map
from .models import Candle
from .structure_v2 import detect_structure

REQUIRED = ("IDM", "LIQUIDITY_SWEEP", "STRUCTURE_SHIFT",
            "DISPLACEMENT", "ORDER_BLOCK", "FVG", "MITIGATION_RETEST")


def _stamp(candles: list[Candle], index: int | None) -> str | None:
    return candles[index].timestamp.isoformat() if index is not None else None


def _stage(candles: list[Candle], name: str, index: int | None,
           reason: str, **extra) -> dict:
    return {"stage": name, "observed": index is not None,
            "at": _stamp(candles, index), "reason": reason,
            **extra}


def analyze_ict_sequence(candles: list[Candle], *,
                         direction: str, as_of: int | None = None,
                         max_sweep_lookback: int = 35,
                         max_retest_bars: int = 20,
                         displacement_atr_ratio: float = 0.8) -> dict:
    """Closed-prefix-only causal sequence, no intrabar event ordering inferred."""
    if direction not in ("BULLISH", "BEARISH"):
        raise ValueError("INVALID_ICT_DIRECTION")
    if max_sweep_lookback < 1 or max_retest_bars < 1 or displacement_atr_ratio <= 0:
        raise ValueError("INVALID_ICT_PARAMETERS")
    if not candles:
        raise ValueError("EMPTY_ICT_INPUT")
    if as_of is None:
        as_of = len(candles)-1
    if not 0 <= as_of < len(candles):
        raise ValueError("INVALID_ICT_AS_OF")
    prefix = candles[:as_of+1]
    if any(not c.complete for c in prefix):
        raise ValueError("INCOMPLETE_ICT_CANDLE")
    if any(a.timestamp >= b.timestamp for a, b in zip(prefix, prefix[1:])):
        raise ValueError("UNORDERED_ICT_CANDLES")
    if len({c.timestamp.date() for c in prefix}) != 1:
        raise ValueError("ICT_SINGLE_SESSION_ONLY")

    bullish = direction == "BULLISH"
    pivots = confirmed_pivots(prefix, k=2)
    breaks = [b for b in detect_structure(prefix, internal_k=2, external_k=5)
              if b.direction == direction and b.tier == "INTERNAL"]
    levels, liquidity_events = liquidity_map(prefix, pivots)
    # For bullish setups, down-wick SSL/EQL sweep supplies liquidity.
    # For bearish setups, up-wick BSL/EQH sweep supplies liquidity.
    sweep_levels = {"SSL", "EQL"} if bullish else {"BSL", "EQH"}
    sweeps = [e for e in liquidity_events
              if e.kind == "SWEEP" and e.level.kind in sweep_levels]
    idms = find_idm(pivots, breaks)
    blocks = find_order_blocks(prefix, breaks)
    fvgs = fair_value_gaps(prefix)
    needed_fvg = "BULLISH_FVG" if bullish else "BEARISH_FVG"
    # Select the latest valid CHoCH/BOS with a preceding sweep, never a
    # post-shift sweep. No sweep => still show latest shift as context.
    valid_pairs = [(b, s) for b in breaks for s in sweeps
                   if 0 < b.candle_index-s.candle_index <= max_sweep_lookback]
    if valid_pairs:
        selected_break, sweep = max(valid_pairs,
                                    key=lambda pair: (pair[0].candle_index,
                                                      pair[1].candle_index))
    else:
        selected_break = breaks[-1] if breaks else None
        sweep = None
    shift_i = selected_break.candle_index if selected_break else None
    sweep_i = sweep.candle_index if sweep else None
    # IDM is an *independent* local pre-break pivot hypothesis: it is NOT
    # automatically labeled grabbed merely because an unrelated sweep occurred.
    idm = next((x for x in reversed(idms)
                if selected_break is not None
                and x.structure_index == selected_break.candle_index), None)
    idm_pivot = next((p for p in pivots if idm is not None
                      and p.index == idm.source_index), None)
    idm_i = idm_pivot.confirmed_at if idm_pivot is not None else None
    idm_swept = bool(idm and idm_pivot and sweep
                     and idm_pivot.confirmed_at < sweep.candle_index
                     and (sweep.level.price <= idm.price if bullish
                          else sweep.level.price >= idm.price))
    # Displacement must be on the close-based break candle, with historical ATR
    # measured before the break, so a later volatility spike cannot help.
    displacement = False
    if selected_break and shift_i >= 15:
        c = prefix[shift_i]
        historical_atr = atr(prefix[:shift_i], length=14)
        body = abs(c.close-c.open)
        displacement = bool(historical_atr and
                            (c.close > c.open if bullish else c.close < c.open)
                            and body >= displacement_atr_ratio*historical_atr)
    # No OB created by or after the shift. It is only confirmed *at* shift.
    block = next((b for b in reversed(blocks) if selected_break
                  and b.structure_index == shift_i
                  and b.confirmed_at == shift_i), None)
    # FVG must exist by the decision bar, nearby the structure shift.
    eligible_fvg = [g for g in fvgs if g.kind == needed_fvg and
                    shift_i is not None and shift_i <= g.created_at <= shift_i+3]
    fvg = eligible_fvg[0] if eligible_fvg else None
    # OB mitigation requires strictly later candle *after* the FVG is
    # available, and a rejection close beyond the block boundary.
    available_i = max(shift_i, fvg.created_at) if shift_i is not None and fvg else None
    mitigation_i = None
    invalidated_i = None
    if block and available_i is not None:
        for i in range(available_i+1, min(as_of+1, available_i+max_retest_bars+1)):
            c = prefix[i]
            invalid = c.close < block.lower if bullish else c.close > block.upper
            if invalid:
                invalidated_i = i
                break
            touched = c.low <= block.upper and c.high >= block.lower
            rejected = c.close > block.upper if bullish else c.close < block.lower
            if touched and rejected:
                mitigation_i = i
                break
    sequence = {
        "IDM": _stage(prefix, "IDM", idm_i,
                      "PROVISIONAL_PRE_BREAK_OPPOSITE_PIVOT" if idm else "NO_CAUSAL_IDM",
                      price=idm.price if idm else None,
                      idm_swept_proxy=idm_swept),
        "LIQUIDITY_SWEEP": _stage(
            prefix, "LIQUIDITY_SWEEP", sweep_i,
            "WICK_BREACH_AND_CLOSE_BACK_INSIDE" if sweep else "NO_PRE_SHIFT_SWEEP",
            kind=sweep.level.kind if sweep else None,
            level=sweep.level.price if sweep else None),
        "STRUCTURE_SHIFT": _stage(
            prefix, "STRUCTURE_SHIFT", shift_i,
            selected_break.kind if selected_break else "NO_CONFIRMED_CLOSE_BREAK",
            kind=selected_break.kind if selected_break else None,
            broken_level=selected_break.broken_pivot.price if selected_break else None),
        "DISPLACEMENT": _stage(
            prefix, "DISPLACEMENT", shift_i if displacement else None,
            "BREAK_BODY_MEETS_PRIOR_ATR" if displacement else "NO_CONFIRMED_DISPLACEMENT"),
        "ORDER_BLOCK": _stage(
            prefix, "ORDER_BLOCK", shift_i if block else None,
            "PRE_SHIFT_OPPOSITE_BODY_CANDIDATE" if block else "NO_ORIGIN_OB",
            lower=block.lower if block else None, upper=block.upper if block else None),
        "FVG": _stage(prefix, "FVG", fvg.created_at if fvg else None,
                      "THREE_BAR_IMBALANCE_CANDIDATE" if fvg else "NO_CAUSAL_NEARBY_FVG",
                      lower=fvg.lower if fvg else None, upper=fvg.upper if fvg else None),
        "MITIGATION_RETEST": _stage(
            prefix, "MITIGATION_RETEST", mitigation_i,
            "POST_CONFIRMATION_OB_REJECTION" if mitigation_i is not None
            else "OB_INVALIDATED_BEFORE_RETEST" if invalidated_i is not None
            else "NO_CAUSAL_POST_FVG_RETEST",
            invalidated_at=_stamp(prefix, invalidated_i)),
    }
    # A sweep of some other pool does not prove IDM itself was taken:
    # the IDM marker is informational unless we can corroborate the grab.
    passed = all(sequence[k]["observed"] for k in REQUIRED) and idm_swept
    return {
        "schema_version": "ict-sequence-1",
        "as_of": prefix[-1].timestamp.isoformat(),
        "direction": direction, "stages": sequence,
        "stage_counts": dict(Counter(
            "OBSERVED" if sequence[k]["observed"] else "MISSING"
            for k in REQUIRED)),
        "ict_sequence_observed": passed,
        "status": "RESEARCH_SEQUENCE_OBSERVED" if passed else "WAIT",
        "missing_stages": [k for k in REQUIRED if not sequence[k]["observed"]]
                           + ([] if idm_swept else ["IDM_SWEEP_CORROBORATION"]),
        "stop_candidate": (min(prefix[sweep_i].low, block.lower) if bullish
                           else max(prefix[sweep_i].high, block.upper))
                          if passed else None,
        "stop_is_verified_protected": False,
        "mitigation_block_is_institutionally_verified": False,
        "order_execution_allowed": False,
        "research_only": True,
    }
