"""Non-repainting, closed-candle SMC primitives (not complete PDF entry schemes)."""
from __future__ import annotations
from dataclasses import dataclass
from .models import Candle, Pivot, StructureEvent, Zone


@dataclass(frozen=True)
class Analysis:
    pivots: tuple[Pivot, ...]
    events: tuple[StructureEvent, ...]
    fvgs: tuple[Zone, ...]
    sweeps: tuple[StructureEvent, ...]
    atr14: float | None


def confirmed_pivots(candles: list[Candle], k: int = 2) -> list[Pivot]:
    if k < 1:
        raise ValueError("k must be >=1")
    result = []
    for i in range(k, len(candles) - k):
        window = candles[i-k:i+k+1]
        if not all(c.complete for c in window):
            continue
        center = candles[i]
        others = window[:k] + window[k+1:]
        if all(center.high > c.high for c in others):
            result.append(Pivot("HIGH", i, center.high, i+k))
        if all(center.low < c.low for c in others):
            result.append(Pivot("LOW", i, center.low, i+k))
    return result


def structure_events(candles: list[Candle], pivots: list[Pivot]) -> list[StructureEvent]:
    """One close-break per confirmed pivot. Regime change labeled CHoCH."""
    by_confirmation: dict[int, list[Pivot]] = {}
    for p in pivots:
        by_confirmation.setdefault(p.confirmed_at, []).append(p)
    active: dict[str, Pivot] = {}
    broken: set[tuple[str, int]] = set()
    regime: str | None = None
    events = []
    for i, candle in enumerate(candles):
        if not candle.complete:
            continue
        # A pivot becomes usable only once its right-hand confirmation candle closes.
        for pivot in by_confirmation.get(i, []):
            active[pivot.kind] = pivot
        for kind, direction, breached in (
            ("HIGH", "BULLISH", lambda p: candle.close > p),
            ("LOW", "BEARISH", lambda p: candle.close < p),
        ):
            pivot = active.get(kind)
            if not pivot or i <= pivot.confirmed_at or (kind, pivot.index) in broken:
                continue
            if breached(pivot.price):
                label = "CHoCH" if regime and regime != direction else "BOS"
                events.append(StructureEvent(label, direction, pivot.price, i))
                broken.add((kind, pivot.index))
                regime = direction
    return events


def fair_value_gaps(candles: list[Candle]) -> list[Zone]:
    zones = []
    for i in range(2, len(candles)):
        a, b, c = candles[i-2:i+1]
        if not (a.complete and b.complete and c.complete):
            continue
        if a.high < c.low:
            zones.append(Zone("BULLISH_FVG", a.high, c.low, i))
        if a.low > c.high:
            zones.append(Zone("BEARISH_FVG", c.high, a.low, i))
    return zones


def liquidity_sweeps(candles: list[Candle], pivots: list[Pivot]) -> list[StructureEvent]:
    events = []
    used = set()
    for i, candle in enumerate(candles):
        if not candle.complete:
            continue
        for p in pivots:
            if p.confirmed_at >= i or (p.kind, p.index) in used:
                continue
            if p.kind == "HIGH" and candle.high > p.price and candle.close < p.price:
                events.append(StructureEvent("BSL_SWEEP", "BEARISH", p.price, i))
                used.add((p.kind, p.index))
            elif p.kind == "LOW" and candle.low < p.price and candle.close > p.price:
                events.append(StructureEvent("SSL_SWEEP", "BULLISH", p.price, i))
                used.add((p.kind, p.index))
    return events


def atr(candles: list[Candle], length: int = 14) -> float | None:
    complete = [c for c in candles if c.complete]
    if len(complete) < length + 1:
        return None
    true_ranges = [
        max(c.high-c.low, abs(c.high-p.close), abs(c.low-p.close))
        for p, c in zip(complete[:-1], complete[1:])
    ]
    return sum(true_ranges[-length:]) / length


def analyze(candles: list[Candle], k: int = 2) -> Analysis:
    if any(candles[i].timestamp >= candles[i+1].timestamp for i in range(len(candles)-1)):
        raise ValueError("candles must have strictly increasing timestamps")
    pivots = confirmed_pivots(candles, k)
    return Analysis(tuple(pivots), tuple(structure_events(candles, pivots)),
                    tuple(fair_value_gaps(candles)),
                    tuple(liquidity_sweeps(candles, pivots)), atr(candles))
