"""V3.4 research-only liquidity target and OB/FVG POI intelligence.

Only confirmed historical candles and existing causal primitives are accepted.
Price levels approximate possible liquidity; they are not observed stop orders.
Never convert these research candidates into live orders or option P&L.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from .advanced import OrderBlock, find_order_blocks
from .decision_v3 import CheckState, ResearchBracket
from .engine import fair_value_gaps
from .liquidity import LiquidityEvent, LiquidityLevel
from .models import Candle, Zone
from .setup_confirmation_v3 import ObservedStage
from .structure_v2 import StructuralBreak


_UPPER = frozenset(("BSL", "EQH", "PDH"))
_LOWER = frozenset(("SSL", "EQL", "PDL"))


@dataclass(frozen=True)
class TargetCandidate:
    price: float
    level_kind: str
    source_indices: tuple[int, ...]
    available_at: datetime
    index_points: float
    index_rr: float | None
    evidence_id: str


@dataclass(frozen=True)
class TargetReview:
    status: str  # CANDIDATE / WAIT / NO_TRADE
    reason: str
    target: TargetCandidate | None
    examined: int

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "reason": self.reason,
            "examined": self.examined,
            "target": None if self.target is None else {
                "price": self.target.price,
                "level_kind": self.target.level_kind,
                "source_indices": list(self.target.source_indices),
                "available_at": self.target.available_at.isoformat(),
                "index_points": self.target.index_points,
                "index_rr": self.target.index_rr,
                "evidence_id": self.target.evidence_id,
            },
            "research_only": True,
        }


@dataclass(frozen=True)
class POICandidate:
    direction: str
    lower: float
    upper: float
    ob_index: int
    fvg_index: int
    available_at: datetime
    evidence_id: str
    retest_index: int | None = None


@dataclass(frozen=True)
class POIReview:
    status: str  # CANDIDATE / WAIT
    reason: str
    zones: tuple[POICandidate, ...]

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "reason": self.reason,
            "zones": [{
                "direction": z.direction, "lower": z.lower, "upper": z.upper,
                "ob_index": z.ob_index, "fvg_index": z.fvg_index,
                "available_at": z.available_at.isoformat(),
                "evidence_id": z.evidence_id,
                "retest_index": z.retest_index,
            } for z in self.zones],
            "research_only": True,
        }


def _observed(candles: list[Candle], *, as_of: datetime) -> None:
    if as_of.tzinfo is None:
        raise ValueError("AS_OF_REQUIRES_OFFSET")
    if any(a.timestamp >= b.timestamp for a, b in zip(candles, candles[1:])):
        raise ValueError("CANDLES_NOT_STRICTLY_ORDERED")
    if any(not c.complete for c in candles):
        raise ValueError("INCOMPLETE_CANDLE")
    if any(c.timestamp > as_of for c in candles):
        raise ValueError("FUTURE_CANDLE")


def review_liquidity_target(*, candles: list[Candle],
                            levels: list[LiquidityLevel],
                            events: list[LiquidityEvent],
                            direction: str, entry: float,
                            stop: float | None = None,
                            symbol: str = "NIFTY",
                            at_index: int | None = None,
                            as_of: datetime,
                            min_index_rr: float = 2.0) -> TargetReview:
    """Nearest *unconsumed*, causally eligible opposing liquidity level.

    A level is consumed on its first SWEEP or RUN at/before the decision bar.
    Missing event history is not silently interpreted as unused: each eligible
    level is independently checked against the available candle history.
    Caller remains responsible for complete-session data verification.
    """
    _observed(candles, as_of=as_of)
    if direction not in ("BULLISH", "BEARISH") or symbol not in ("NIFTY", "SENSEX"):
        raise ValueError("INVALID_DIRECTION_OR_SYMBOL")
    if not isfinite(entry) or entry <= 0 or (stop is not None and
            (not isfinite(stop) or stop <= 0)):
        raise ValueError("INVALID_ENTRY_OR_STOP")
    if not isfinite(min_index_rr) or min_index_rr <= 0:
        raise ValueError("INVALID_INDEX_RR")
    end = len(candles)-1 if at_index is None else at_index
    if not 0 <= end < len(candles):
        return TargetReview("WAIT", "NO_DECISION_CANDLE", None, 0)
    if candles[end].timestamp > as_of:
        raise ValueError("DECISION_BAR_AFTER_AS_OF")
    if stop is not None and not (
            stop < entry if direction == "BULLISH" else stop > entry):
        raise ValueError("STOP_DIRECTION_MISMATCH")
    allowed = _UPPER if direction == "BULLISH" else _LOWER
    # Validate supplied event indices and sources to avoid pretending arbitrary
    # lookahead events were observed.
    for ev in events:
        if not 0 <= ev.candle_index < len(candles):
            raise ValueError("INVALID_LIQUIDITY_EVENT_INDEX")
    eligible = []
    for lev in levels:
        if lev.kind not in allowed or not isfinite(lev.price) or lev.price <= 0:
            continue
        if lev.created_at < 0 or lev.eligible_from <= lev.created_at:
            # PDH/PDL may be eligible immediately on the next session's first
            # candle; no event at creation is counted as future evidence.
            if lev.kind not in ("PDH", "PDL") or lev.eligible_from != lev.created_at:
                continue
        if lev.created_at > end or lev.eligible_from > end:
            continue
        if direction == "BULLISH" and lev.price <= entry:
            continue
        if direction == "BEARISH" and lev.price >= entry:
            continue
        # Never use a level if ANY observed completed candle crossed it after
        # eligibility. Even a wick means the original pool has been contacted.
        touched = any(
            (c.high > lev.price if lev.kind in _UPPER else c.low < lev.price)
            for c in candles[max(lev.eligible_from, 0):end+1]
        )
        consumed_event = any(
            ev.level == lev and ev.candle_index <= end
            and ev.kind in ("SWEEP", "RUN") for ev in events
        )
        if touched or consumed_event:
            continue
        eligible.append(lev)
    if not eligible:
        return TargetReview("WAIT", "NO_UNCONSUMED_OPPOSING_LIQUIDITY", None, 0)
    lev = min(eligible, key=lambda x: (x.price, x.eligible_from)) if direction == "BULLISH" else max(
        eligible, key=lambda x: (x.price, -x.eligible_from))
    points = abs(lev.price-entry)
    rr = points / abs(entry-stop) if stop is not None else None
    minimum = 50 if symbol == "NIFTY" else 100
    candidate = TargetCandidate(
        lev.price, lev.kind, lev.source_indices,
        candles[lev.created_at].timestamp, points, rr,
        f"ltf:liquidity:{lev.kind}:{lev.created_at}:{','.join(map(str, lev.source_indices))}",
    )
    if points < minimum:
        return TargetReview("NO_TRADE", "INDEX_TARGET_TOO_SMALL", candidate, len(eligible))
    if rr is not None and rr < min_index_rr:
        return TargetReview("NO_TRADE", "INDEX_RR_BELOW_MINIMUM", candidate, len(eligible))
    return TargetReview("CANDIDATE", "OPPOSING_LIQUIDITY_RESEARCH_CANDIDATE", candidate, len(eligible))


def review_ob_fvg_poi(*, candles: list[Candle],
                      breaks: list[StructuralBreak],
                      direction: str, as_of: datetime,
                      max_age_bars: int = 50) -> POIReview:
    """Find overlap between confirmed opposite-candle OB and directional FVG.

    The overlap is a candidate POI. No full institutional OB, displacement or
    market-structure shift is implied; retest is reported separately.
    """
    _observed(candles, as_of=as_of)
    if direction not in ("BULLISH", "BEARISH") or max_age_bars < 1:
        raise ValueError("INVALID_POI_PARAMETERS")
    expected = "BULLISH_FVG" if direction == "BULLISH" else "BEARISH_FVG"
    for event in breaks:
        if not 0 <= event.candle_index < len(candles):
            raise ValueError("INVALID_STRUCTURE_EVENT_INDEX")
    blocks = find_order_blocks(candles, list(breaks))
    gaps = fair_value_gaps(candles)
    zones = []
    n = len(candles)
    for ob in blocks:
        if ob.direction != direction or n-1-ob.confirmed_at > max_age_bars:
            continue
        for fvg in gaps:
            if fvg.kind != expected or fvg.created_at < ob.confirmed_at:
                continue
            # Require FVG reasonably near the break; late unrelated FVGs
            # cannot be retroactively associated with this OB.
            if fvg.created_at - ob.confirmed_at > 3:
                continue
            lo = max(ob.lower, fvg.lower)
            hi = min(ob.upper, fvg.upper)
            if not lo < hi:
                continue
            available = max(ob.confirmed_at, fvg.created_at)
            # Any prior post-confirmation full boundary close invalidates zone.
            invalidated = any(
                c.close < lo if direction == "BULLISH" else c.close > hi
                for c in candles[available+1:]
            )
            if invalidated:
                continue
            retests = [
                i for i in range(available+1, n)
                if candles[i].low <= hi and candles[i].high >= lo
                and (candles[i].close > hi if direction == "BULLISH"
                     else candles[i].close < lo)
            ]
            zones.append(POICandidate(
                direction, lo, hi, ob.source_index, fvg.created_at,
                candles[available].timestamp,
                f"ltf:ob-fvg:{ob.source_index}:{fvg.created_at}",
                retests[0] if retests else None,
            ))
    zones.sort(key=lambda z: (z.available_at, z.ob_index, z.fvg_index),
               reverse=True)
    return POIReview("CANDIDATE" if zones else "WAIT",
                     "OB_FVG_CONFLUENCE_FOUND_NOT_VERIFIED_POI" if zones else "NO_VALID_OB_FVG_OVERLAP",
                     tuple(zones))


def index_bracket_from_target(*, entry: float, stop: float,
                              direction: str,
                              review: TargetReview) -> ResearchBracket | None:
    """Only an index target meeting index gates can form a research bracket."""
    if review.status != "CANDIDATE" or review.target is None:
        return None
    return ResearchBracket(entry, stop, review.target.price, direction)


def candidate_poi_stage(review: POIReview) -> ObservedStage:
    """POI candidate alone is never enough to set HTF_POI=PASS."""
    return ObservedStage(
        "HTF_POI", CheckState.PENDING,
        "Candidate OB/FVG overlap requires HTF origin, freshness and mitigation confirmation"
        if review.zones else review.reason,
        source_id=review.zones[0].evidence_id if review.zones else None,
    )
