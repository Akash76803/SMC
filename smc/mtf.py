"""Causally aligned HTF/LTF confirmation (only completed higher timeframe bars)."""
from __future__ import annotations
from datetime import timedelta
from .models import Candle
from .structure_v2 import StructuralBreak

def aligned_bias(ltf_candle: Candle, htf_candles: list[Candle],
                 htf_events: list[StructuralBreak],
                 *, duration_minutes: int) -> str | None:
    """Return last HTF external BOS/CHoCH direction known at LTF decision time.

    Each HTF candle timestamp denotes candle START. HTF candle is usable only
    after its full duration has elapsed, regardless of complete flag mistakes.
    """
    if duration_minutes<=0:
        raise ValueError("duration must be positive")
    if not ltf_candle.complete:
        return None
    eligible={i for i,c in enumerate(htf_candles)
              if c.complete and
              c.timestamp+timedelta(minutes=duration_minutes)<=ltf_candle.timestamp}
    events=[e for e in htf_events if e.tier=="EXTERNAL" and
            e.candle_index in eligible]
    return max(events,key=lambda e:e.candle_index).direction if events else None

def confirm_ltf_direction(ltf_direction: str, ltf_candle: Candle,
                          htf_candles: list[Candle],
                          htf_events: list[StructuralBreak],
                          *, duration_minutes: int) -> bool:
    return aligned_bias(ltf_candle,htf_candles,htf_events,
                        duration_minutes=duration_minutes)==ltf_direction
