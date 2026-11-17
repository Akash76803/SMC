"""V3.9C causal continuation evidence enrichment, not executable advice.

Three independent research lenses:
- confirmed opposite pivot near BOS (provisional protected-swing proxy)
- as-of-confirmation OB/FVG overlap and retest (never verified HTF POI)
- ranked observed T1/T2/T3 liquidity pools (nearest remains the gate)
"""
from __future__ import annotations

from .continuation_v3 import ContinuationObservation
from .engine import confirmed_pivots
from .models import Candle
from .multi_target_v3 import rank_liquidity_targets
from .phase2 import scan
from .poi_liquidity_v3 import review_ob_fvg_poi


def enrich_continuation(*, symbol: str, candles: list[Candle],
                        observation: ContinuationObservation,
                        min_target_points: float | None = None) -> dict:
    if symbol not in ("NIFTY", "SENSEX"):
        raise ValueError("INVALID_RESEARCH_SYMBOL")
    if not candles or any(not c.complete for c in candles):
        raise ValueError("INCOMPLETE_RESEARCH_INPUT")
    if any(a.timestamp >= b.timestamp for a, b in zip(candles, candles[1:])):
        raise ValueError("UNORDERED_RESEARCH_INPUT")
    if len({c.timestamp.date() for c in candles}) != 1:
        raise ValueError("CROSS_SESSION_RESEARCH_INPUT")
    bi, pi, ci = (observation.bos_index, observation.pullback_index,
                  observation.confirm_index)
    if not 0 <= bi < pi < ci < len(candles):
        raise ValueError("INVALID_RESEARCH_EVENT_INDICES")
    direction = observation.direction
    if direction not in ("BULLISH", "BEARISH"):
        raise ValueError("INVALID_RESEARCH_DIRECTION")
    prefix = candles[:ci + 1]
    at = prefix[-1].timestamp
    bullish = direction == "BULLISH"
    entry = candles[ci].close
    stop = candles[pi].low if bullish else candles[pi].high
    risk_valid = stop < entry if bullish else stop > entry

    # Strictly causal at the original BOS close: a pivot confirmed after the
    # BOS is not a candidate for the protected structure at BOS.
    opposite = "LOW" if bullish else "HIGH"
    pivots = confirmed_pivots(candles[:bi + 1], k=2)
    prior = [p for p in pivots
             if p.kind == opposite and p.confirmed_at < bi]
    protected = max(prior, key=lambda p: (p.confirmed_at, p.index),
                    default=None)
    protected_review = {
        "status": "PROVISIONAL" if protected else "UNAVAILABLE",
        "reason": ("PRIOR_CONFIRMED_OPPOSITE_PIVOT_NOT_VERIFIED_PROTECTED"
                   if protected else "NO_PRIOR_CONFIRMED_OPPOSITE_PIVOT"),
        "price": protected.price if protected else None,
        "pivot_index": protected.index if protected else None,
        "confirmed_at": (candles[protected.confirmed_at].timestamp.isoformat()
                         if protected else None),
        "is_verified_protected_structure": False,
    }

    history = scan(prefix)
    poi = review_ob_fvg_poi(
        candles=prefix, breaks=list(history.structure_events),
        direction=direction, as_of=at)
    # Only evidence known by the decision close may be displayed, and a
    # candidate's own retest must occur at/before confirmation.
    retested = [z for z in poi.zones if z.retest_index is not None
                and pi <= z.retest_index <= ci
                and z.available_at <= at]
    candidate = retested[0] if retested else None
    poi_review = {
        "status": "PROVISIONAL" if candidate else "UNVERIFIED",
        "reason": ("LTF_OB_FVG_RETEST_PROXY_NOT_VERIFIED_HTF_POI"
                   if candidate else "NO_CAUSAL_OB_FVG_RETEST_AT_SETUP"),
        "lower": candidate.lower if candidate else None,
        "upper": candidate.upper if candidate else None,
        "evidence_id": candidate.evidence_id if candidate else None,
        "retest_at": (candles[candidate.retest_index].timestamp.isoformat()
                      if candidate else None),
        "is_verified_htf_poi": False,
    }

    targets = None
    if risk_valid:
        targets = rank_liquidity_targets(
            candles=prefix, levels=list(history.levels),
            events=list(history.liquidity_events), direction=direction,
            entry=entry, stop=stop, symbol=symbol, as_of=at,
            min_target_points=min_target_points)
    ladder = targets.as_dict() if targets is not None else {
        "status": "NO_TRADE", "reason": "INVALID_STOP_REFERENCE",
        "targets": [], "expected_index_rr": None,
        "maximum_observed_index_rr": None,
        "research_only": True,
    }
    return {
        "protected_structure": protected_review,
        "poi": poi_review,
        "index_targets": ladder,
        "status": "RESEARCH_ONLY",
        "no_trade_authorization": True,
    }
