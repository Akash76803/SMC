"""Causally confirmed preliminary internal/external structure model.

This is a configurable engineering definition; do not label it as a
verified implementation of every protected-swing convention in the PDFs.
"""
from __future__ import annotations

from dataclasses import dataclass

from .engine import confirmed_pivots
from .models import Candle, Pivot


@dataclass(frozen=True)
class StructuralBreak:
    kind: str  # BOS / CHoCH
    direction: str
    tier: str  # INTERNAL / EXTERNAL
    broken_pivot: Pivot
    candle_index: int
    protected_pivot: Pivot | None


def detect_structure(candles: list[Candle], *,
                     internal_k: int = 2, external_k: int = 5,
                     buffer: float = 0.0) -> list[StructuralBreak]:
    if internal_k < 1 or external_k <= internal_k or buffer < 0:
        raise ValueError("require 1 <= internal_k < external_k and buffer >= 0")
    if any(candles[i].timestamp >= candles[i+1].timestamp
           for i in range(len(candles)-1)):
        raise ValueError("candles must be ordered")
    events: list[StructuralBreak] = []
    for tier, k in (("INTERNAL", internal_k), ("EXTERNAL", external_k)):
        pivots = confirmed_pivots(candles, k=k)
        confirmed: dict[int, list[Pivot]] = {}
        for p in pivots:
            confirmed.setdefault(p.confirmed_at, []).append(p)
        active: dict[str, Pivot] = {}
        broken: set[tuple[str, int]] = set()
        trend: str | None = None
        protected: Pivot | None = None
        for i, c in enumerate(candles):
            if not c.complete:
                continue
            for p in confirmed.get(i, []):
                active[p.kind] = p
            # A single candle could gap over both old pivots. Such ambiguous
            # data is ignored rather than emitting contradictory breaks.
            possible = []
            for kind, direction in (("HIGH", "BULLISH"), ("LOW", "BEARISH")):
                p = active.get(kind)
                if not p or i <= p.confirmed_at or (p.kind, p.index) in broken:
                    continue
                if (kind == "HIGH" and c.close > p.price + buffer) or (
                    kind == "LOW" and c.close < p.price - buffer
                ):
                    possible.append((p, direction))
            if len(possible) != 1:
                continue
            p, direction = possible[0]
            # Opposite most-recent *confirmed* swing is a provisional
            # protected-swing proxy; fine-grained IDM rules remain pending.
            opposite = active.get("LOW" if direction == "BULLISH" else "HIGH")
            kind = "CHoCH" if trend is not None and trend != direction else "BOS"
            if kind == "CHoCH" and protected is not None:
                # Change of character requires breaking the prior protected swing.
                # If it is not that level, do not call it a confirmed CHoCH.
                if p.kind != protected.kind or p.index != protected.index:
                    broken.add((p.kind, p.index))
                    continue
            events.append(StructuralBreak(kind, direction, tier, p, i, protected))
            broken.add((p.kind, p.index))
            trend = direction
            protected = opposite
    return sorted(events, key=lambda e: (e.candle_index, e.tier))
