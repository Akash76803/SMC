"""Read-only Phase 2 liquidity and structure scanner for historical candles."""
from __future__ import annotations
from dataclasses import dataclass

from .engine import analyze
from .liquidity import LiquidityEvent, LiquidityLevel, liquidity_map
from .models import Candle
from .structure_v2 import StructuralBreak, detect_structure


@dataclass(frozen=True)
class Phase2Scan:
    levels: tuple[LiquidityLevel, ...]
    liquidity_events: tuple[LiquidityEvent, ...]
    structure_events: tuple[StructuralBreak, ...]
    atr14: float | None
    status: str = "RESEARCH_ONLY_NO_TRADE"


def scan(candles: list[Candle], *, internal_k: int = 2,
         external_k: int = 5, equal_tolerance: float = 2.0,
         break_buffer: float = 0.0) -> Phase2Scan:
    if any(candles[i].timestamp >= candles[i+1].timestamp
           for i in range(len(candles)-1)):
        raise ValueError("candles must be ordered")
    basic = analyze(candles, k=internal_k)
    levels, sweeps = liquidity_map(
        candles, list(basic.pivots),
        equal_tolerance=equal_tolerance, break_buffer=break_buffer
    )
    structures = detect_structure(
        candles, internal_k=internal_k, external_k=external_k,
        buffer=break_buffer
    )
    return Phase2Scan(tuple(levels), tuple(sweeps),
                      tuple(structures), basic.atr14)
