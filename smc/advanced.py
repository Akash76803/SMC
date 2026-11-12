"""Phase 3.2: causal SMC research primitives, not trading advice.

Order blocks and IDM are *engineering hypotheses* to be validated with PDF
fixtures and historical out-of-sample tests, not institutional order evidence.
"""
from __future__ import annotations
from dataclasses import dataclass
from .models import Candle, Pivot
from .structure_v2 import StructuralBreak
from .liquidity import LiquidityLevel

@dataclass(frozen=True)
class OrderBlock:
    direction: str
    lower: float
    upper: float
    source_index: int
    confirmed_at: int
    structure_index: int
    refined: bool = False

@dataclass(frozen=True)
class IDM:
    direction: str
    price: float
    source_index: int
    confirmed_at: int
    structure_index: int

@dataclass(frozen=True)
class VolatilityResult:
    accepted: bool
    atr: float | None
    target_points: float
    atr_ratio: float | None
    reason: str

def find_order_blocks(candles: list[Candle], breaks: list[StructuralBreak],
                      *, lookback: int = 8) -> list[OrderBlock]:
    """Opposite-colored origin candle before confirmed structural break.

    Source candle must precede the break; use only fully closed intervening bars.
    This does NOT assert actual institutional order locations.
    """
    if lookback < 1:
        raise ValueError("lookback must be positive")
    blocks = []
    seen = set()
    for event in sorted(breaks, key=lambda e: e.candle_index):
        i = event.candle_index
        if not 0 <= i < len(candles) or not candles[i].complete:
            continue
        for j in range(i-1, max(-1,i-lookback-1), -1):
            c = candles[j]
            if not c.complete:
                continue
            opposite = c.close < c.open if event.direction == "BULLISH" else c.close > c.open
            if opposite and (event.direction,j) not in seen:
                blocks.append(OrderBlock(event.direction,c.low,c.high,j,i,i))
                seen.add((event.direction,j))
                break
    return blocks

def refine_order_block(block: OrderBlock, htf_candles: list[Candle],
                       ltf_candles: list[Candle]) -> OrderBlock:
    """Refine only with subcandles fully inside parent candle's time window.

    HTF duration is inferred from next HTF candle timestamp, requiring it to exist.
    No future subcandles beyond the structure-confirmation time are used.
    """
    i=block.source_index
    if i<0 or i+1>=len(htf_candles):
        return block
    start=htf_candles[i].timestamp
    end=htf_candles[i+1].timestamp
    eligible=[(j,c) for j,c in enumerate(ltf_candles)
              if c.complete and start<=c.timestamp<end
              and block.lower<=c.low<=c.high<=block.upper]
    if not eligible:
        return block
    matches=[(j,c) for j,c in eligible if
             (c.close<c.open if block.direction=="BULLISH" else c.close>c.open)]
    if not matches:
        return block
    _, chosen=matches[-1]
    if chosen.high-chosen.low >= block.upper-block.lower:
        return block
    return OrderBlock(block.direction,chosen.low,chosen.high,block.source_index,
                      block.confirmed_at,block.structure_index,True)

def find_idm(pivots: list[Pivot], breaks: list[StructuralBreak]) -> list[IDM]:
    """Pre-break opposing confirmed pivot as provisional inducement candidate.

    Critical: a candidate is NOT a verified liquidity grab or entry trigger.
    """
    results=[]
    for event in breaks:
        kind="LOW" if event.direction=="BULLISH" else "HIGH"
        eligible=[p for p in pivots if p.kind==kind
                  and p.confirmed_at<event.candle_index
                  and p.index<event.broken_pivot.index]
        if eligible:
            p=max(eligible,key=lambda x:x.confirmed_at)
            results.append(IDM(event.direction,p.price,p.index,
                               event.candle_index,event.candle_index))
    return results

def qualify_atr(atr_value: float | None, target_points: float,
                *, max_target_atr: float=4.0) -> VolatilityResult:
    """Heuristic feasibility screen, not a target-hit probability."""
    if target_points<=0 or max_target_atr<=0:
        raise ValueError("invalid target/ATR threshold")
    if atr_value is None or atr_value<=0:
        return VolatilityResult(False,atr_value,target_points,None,"ATR_UNAVAILABLE")
    ratio=target_points/atr_value
    return VolatilityResult(ratio<=max_target_atr,atr_value,target_points,ratio,
                            "ATR_PASS" if ratio<=max_target_atr else "TARGET_TOO_LARGE_VS_ATR")

def select_liquidity_target(entry: float, direction: str,
                            levels: list[LiquidityLevel], at_index: int,
                            *, invalidated: set[tuple[str,float]] | None=None
                            ) -> float | None:
    """Nearest eligible opposing liquidity level strictly ahead of entry.

    Requires caller to omit any previously swept or invalidated levels.
    No target is fabricated if no suitable level exists.
    """
    if direction not in ("BULLISH","BEARISH"):
        raise ValueError("unsupported direction")
    blocked=invalidated or set()
    opposing={"BSL","EQH","PDH"} if direction=="BULLISH" else {"SSL","EQL","PDL"}
    candidates=[l.price for l in levels if l.kind in opposing
                and l.eligible_from<=at_index and l.created_at<=at_index
                and (l.kind,l.price) not in blocked
                and (l.price>entry if direction=="BULLISH" else l.price<entry)]
    if not candidates:
        return None
    return min(candidates) if direction=="BULLISH" else max(candidates)
