"""Phase 1: causal three-candle STH/STL, nested ITH/ITL, and structural breaks.

Research interpretation of supplied SMC lecture definitions, not a claim of
observing institutional orders. Closed candles only; no future bars.
This opt-in module does not replace the existing structure_v2/replay engine.
"""
from __future__ import annotations

from dataclasses import dataclass
from .models import Candle, Pivot


@dataclass(frozen=True)
class HierarchyPoint:
    kind: str  # STH / STL / ITH / ITL
    pivot: Pivot
    confirmed_at: int
    left_pivot_index: int | None = None
    right_pivot_index: int | None = None


@dataclass(frozen=True)
class StructureMark:
    kind: str  # BOS / CHoCH / SWEEP
    direction: str  # BULLISH / BEARISH (break direction)
    tier: str  # SHORT / INTERMEDIATE
    level: float
    origin_index: int
    confirmed_at: int
    protected_index: int | None = None


@dataclass(frozen=True)
class IDMMark:
    """Nearest confirmed minor pivot to an already confirmed structural extreme.

    A candidate is usable only once its own pivot and the structural extreme
    have been confirmed. A first touch/wick is the *event*, not body close.
    """
    direction: str
    level: float
    extreme_index: int
    minor_index: int
    eligible_from: int
    swept_at: int


def _validate(candles: list[Candle]) -> None:
    if any(a.timestamp >= b.timestamp for a, b in zip(candles, candles[1:])):
        raise ValueError("timestamps must be strictly increasing")


def three_candle_points(candles: list[Candle]) -> tuple[HierarchyPoint, ...]:
    """Strict 3-bar highs/lows; pivot center i is known at close of i+1."""
    _validate(candles)
    short: list[HierarchyPoint] = []
    for i in range(1, len(candles) - 1):
        a, b, c = candles[i-1:i+2]
        if not (a.complete and b.complete and c.complete):
            continue
        if b.high > a.high and b.high > c.high:
            short.append(HierarchyPoint("STH", Pivot("HIGH", i, b.high, i+1), i+1))
        if b.low < a.low and b.low < c.low:
            short.append(HierarchyPoint("STL", Pivot("LOW", i, b.low, i+1), i+1))
    return tuple(sorted(short, key=lambda p: (p.confirmed_at, p.pivot.index, p.kind)))


def structure_hierarchy(candles: list[Candle]) -> tuple[HierarchyPoint, ...]:
    """ITH = higher STH than adjacent STH; ITL = lower STL than adjacent STL.

    The center pivot becomes ITH/ITL only after the right neighbor's 3-bar
    confirmation. Equal highs/lows intentionally yield no hierarchy point.
    """
    short = three_candle_points(candles)
    intermediate: list[HierarchyPoint] = []
    for kind, outer, comparator in (
        ("STH", "ITH", lambda a, b: a > b),
        ("STL", "ITL", lambda a, b: a < b),
    ):
        seq = sorted((p for p in short if p.kind == kind),
                     key=lambda p: p.pivot.index)
        for j in range(1, len(seq)-1):
            left, mid, right = seq[j-1:j+2]
            if comparator(mid.pivot.price, left.pivot.price) and comparator(
                    mid.pivot.price, right.pivot.price):
                intermediate.append(HierarchyPoint(
                    outer, mid.pivot, right.confirmed_at,
                    left.pivot.index, right.pivot.index))
    return tuple(sorted([*short, *intermediate],
                        key=lambda p: (p.confirmed_at, p.pivot.index, p.kind)))


def _tier_events(candles: list[Candle],
                 points: tuple[HierarchyPoint, ...],
                 high_kind: str, low_kind: str, tier: str,
                 buffer: float) -> list[StructureMark]:
    eligible = sorted((p for p in points if p.kind in (high_kind, low_kind)),
                      key=lambda p: (p.confirmed_at, p.pivot.index))
    by_confirmation: dict[int, list[HierarchyPoint]] = {}
    for p in eligible:
        by_confirmation.setdefault(p.confirmed_at, []).append(p)
    active: dict[str, HierarchyPoint] = {}
    used: set[tuple[str, int]] = set()
    wick_extreme: dict[tuple[str, int], float] = {}
    trend: str | None = None
    protected: HierarchyPoint | None = None
    output: list[StructureMark] = []
    for i, candle in enumerate(candles):
        if not candle.complete:
            continue
        for p in by_confirmation.get(i, []):
            active[p.kind] = p
        candidates: list[tuple[str, HierarchyPoint, float, bool]] = []
        for kind, direction in ((high_kind, "BULLISH"), (low_kind, "BEARISH")):
            reversal = trend is not None and trend != direction
            p = (protected if reversal and protected is not None
                 else active.get(kind))
            if p is None or p.kind != kind or p.confirmed_at >= i:
                continue
            key = (kind, p.pivot.index)
            if key in used:
                continue
            threshold = wick_extreme.get(key, p.pivot.price)
            breach = (candle.high > threshold + buffer if direction == "BULLISH"
                      else candle.low < threshold - buffer)
            close_break = (candle.close > threshold + buffer if direction == "BULLISH"
                           else candle.close < threshold - buffer)
            if breach or close_break:
                candidates.append((direction, p, threshold, close_break))
        # Can't assign direction if both sides of a range break on same bar.
        if len(candidates) != 1:
            continue
        direction, p, threshold, close_break = candidates[0]
        key = (p.kind, p.pivot.index)
        if close_break:
            opposite = active.get(low_kind if direction == "BULLISH" else high_kind)
            label = "CHoCH" if trend is not None and trend != direction else "BOS"
            output.append(StructureMark(
                label, direction, tier, threshold, p.pivot.index, i,
                protected.pivot.index if protected else None))
            used.add(key)
            trend = direction
            protected = opposite
        else:
            output.append(StructureMark("SWEEP", direction, tier,
                                        threshold, p.pivot.index, i,
                                        protected.pivot.index if protected else None))
            wick_extreme[key] = (max(threshold, candle.high) if direction == "BULLISH"
                                 else min(threshold, candle.low))
    return output


def detect_hierarchical_structure(candles: list[Candle], *,
                                  buffer: float = 0.0) -> tuple[StructureMark, ...]:
    """Research structure events from confirmed short and intermediate pivots."""
    if buffer < 0:
        raise ValueError("buffer must be nonnegative")
    points = structure_hierarchy(candles)
    short = _tier_events(candles, points, "STH", "STL", "SHORT", buffer)
    intermediate = _tier_events(candles, points, "ITH", "ITL", "INTERMEDIATE", buffer)
    return tuple(sorted([*short, *intermediate],
                        key=lambda e: (e.confirmed_at, e.tier, e.kind)))


def detect_idm_touches(candles: list[Candle]) -> tuple[IDMMark, ...]:
    """Conservative nearest left STH/STL touch after an opposite short extreme.

    This is a *candidate* IDM proxy, not the full lecture-3 multi-swing
    invalid/valid classification. The touching candle cannot also be the
    confirmation candle. Each pair can produce at most one event.
    """
    short = three_candle_points(candles)
    candidates: list[tuple[str, HierarchyPoint, HierarchyPoint]] = []
    chronological = sorted(short, key=lambda p: p.pivot.index)
    for j, extreme in enumerate(chronological):
        target_kind = "STL" if extreme.kind == "STH" else "STH"
        left = next((p for p in reversed(chronological[:j])
                     if p.kind == target_kind), None)
        if left is None:
            continue
        candidates.append(("BEARISH" if target_kind == "STL" else "BULLISH",
                           extreme, left))
    output = []
    for direction, extreme, minor in candidates:
        start = max(extreme.confirmed_at, minor.confirmed_at)+1
        for i in range(start, len(candles)):
            candle = candles[i]
            if not candle.complete:
                continue
            touched = (candle.low <= minor.pivot.price if direction == "BEARISH"
                       else candle.high >= minor.pivot.price)
            if touched:
                output.append(IDMMark(direction, minor.pivot.price,
                                      extreme.pivot.index, minor.pivot.index,
                                      start, i))
                break
    return tuple(sorted(output, key=lambda p: (p.swept_at, p.extreme_index)))
