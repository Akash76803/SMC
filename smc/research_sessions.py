"""Explicit research-only normalization for known November 2026 NIFTY data.

The exchange confirmed a 2026-11-08 special Muhurat session. This normal
research profile excludes that day entirely; special sessions require
separate price/HTF alignment modeling. Regular dates retain ONLY 1-minute
close-times 09:16..15:15 IST, dropping unclassified closing-tail records.
No OHLC interpolation or conversion of out-of-session data is performed.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date,time
from typing import Sequence
from zoneinfo import ZoneInfo
from .models import Candle

IST=ZoneInfo("Asia/Kolkata")
SPECIAL_DAYS=frozenset({date(2026,11,8)})
FIRST=time(9,16)
LAST=time(15,15)

@dataclass(frozen=True)
class Normalization:
    candles:tuple[Candle,...]
    removed_special:int
    removed_closing_tail:int

def regular_november_2026(candles:Sequence[Candle])->Normalization:
    """Conservative explicit subset for the observed NIFTY 2026-11 range."""
    if not candles:
        raise ValueError("NO_CANDLES")
    kept=[]
    special=tail=0
    for c in candles:
        dt=c.timestamp.astimezone(IST)
        if dt.date() in SPECIAL_DAYS:
            special+=1
            continue
        if dt.time()>LAST:
            tail+=1
            continue
        # Unexpected early timestamps remain in the dataset so the session
        # audit can reject them rather than silently changing the input.
        kept.append(c)
    if not kept:
        raise ValueError("NO_REGULAR_CANDLES_AFTER_FILTER")
    return Normalization(tuple(kept),special,tail)

def regular_htf_without_special(htf:Sequence[Candle])->tuple[Candle,...]:
    """Remove only the documented special day; the HTF validator still runs."""
    return tuple(c for c in htf if c.timestamp.astimezone(IST).date() not in SPECIAL_DAYS)
