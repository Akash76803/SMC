"""Causal liquidity map. Zones indicate price-based proxies, not observed stop orders.

All decisions use closed candles and pivots confirmed at or before the evaluated bar.
Session boundary is Asia/Kolkata (exchange-local calendar day).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo

from .models import Candle, Pivot

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class LiquidityLevel:
    kind: str  # BSL, SSL, EQH, EQL, PDH, PDL
    price: float
    created_at: int
    source_indices: tuple[int, ...]
    eligible_from: int
    strength: int = 1


@dataclass(frozen=True)
class LiquidityEvent:
    kind: str  # SWEEP or RUN
    level: LiquidityLevel
    candle_index: int
    direction: str  # BULLISH or BEARISH direction of break
    breach: float


def previous_day_levels(candles: list[Candle]) -> list[LiquidityLevel]:
    """Previous *observed* session H/L: only prior completed session candles.

    On each new exchange-local date, levels become active for that date.
    Candle ingestion must contain a complete prior session: the caller is
    responsible for detecting missing sessions/holidays/data gaps.
    """
    daily: dict[date, list[tuple[int, Candle]]] = {}
    for i, c in enumerate(candles):
        if c.complete:
            daily.setdefault(c.timestamp.astimezone(IST).date(), []).append((i, c))
    days = sorted(daily)
    output: list[LiquidityLevel] = []
    for pos in range(1, len(days)):
        prev = daily[days[pos - 1]]
        current = daily[days[pos]]
        first_index = current[0][0]
        high_idx, high_candle = max(prev, key=lambda pair: pair[1].high)
        low_idx, low_candle = min(prev, key=lambda pair: pair[1].low)
        output.extend([
            LiquidityLevel("PDH", high_candle.high, first_index, (high_idx,), first_index),
            LiquidityLevel("PDL", low_candle.low, first_index, (low_idx,), first_index),
        ])
    return output


def swing_liquidity(pivots: list[Pivot]) -> list[LiquidityLevel]:
    """Confirmed pivots create BSL/SSL levels starting the NEXT candle."""
    return [
        LiquidityLevel(
            "BSL" if p.kind == "HIGH" else "SSL",
            p.price, p.confirmed_at, (p.index,), p.confirmed_at + 1
        )
        for p in pivots
    ]


def equal_levels(pivots: list[Pivot], tolerance: float,
                 max_gap: int = 100) -> list[LiquidityLevel]:
    """Pair same-side confirmed pivots. No look-ahead / no repeated pairs."""
    if tolerance < 0 or max_gap < 1:
        raise ValueError("invalid cluster parameters")
    output: list[LiquidityLevel] = []
    by_kind = {"HIGH": [], "LOW": []}
    for p in sorted(pivots, key=lambda item: item.confirmed_at):
        previous = [
            x for x in by_kind[p.kind]
            if p.index - x.index <= max_gap and abs(p.price - x.price) <= tolerance
        ]
        if previous:
            near = previous[-1]
            output.append(LiquidityLevel(
                "EQH" if p.kind == "HIGH" else "EQL",
                (near.price + p.price) / 2,
                p.confirmed_at,
                (near.index, p.index),
                p.confirmed_at + 1,
                2,
            ))
        by_kind[p.kind].append(p)
    return output


def classify_liquidity_events(candles: list[Candle],
                              levels: list[LiquidityLevel],
                              *,
                              break_buffer: float = 0.0) -> list[LiquidityEvent]:
    """First decisive post-creation breach of each level.

    Sweep: wick breaches beyond buffer, candle closes back inside.
    Run: candle CLOSES beyond the buffered level. No repeated events.
    A level created by the current candle is never eligible.
    """
    if break_buffer < 0:
        raise ValueError("break_buffer must be non-negative")
    output: list[LiquidityEvent] = []
    for level in levels:
        upper = level.kind in ("BSL", "EQH", "PDH")
        for i in range(level.eligible_from, len(candles)):
            c = candles[i]
            if not c.complete:
                continue
            if upper:
                breached = c.high > level.price + break_buffer
                run = c.close > level.price + break_buffer
                direction = "BULLISH"
                amount = c.high - level.price
            else:
                breached = c.low < level.price - break_buffer
                run = c.close < level.price - break_buffer
                direction = "BEARISH"
                amount = level.price - c.low
            if breached:
                output.append(LiquidityEvent(
                    "RUN" if run else "SWEEP", level, i, direction, amount
                ))
                break
    return sorted(output, key=lambda e: (e.candle_index, e.level.kind, e.level.price))


def liquidity_map(candles: list[Candle], pivots: list[Pivot],
                  *, equal_tolerance: float = 2.0,
                  break_buffer: float = 0.0
                  ) -> tuple[list[LiquidityLevel], list[LiquidityEvent]]:
    levels = (swing_liquidity(pivots)
              + equal_levels(pivots, tolerance=equal_tolerance)
              + previous_day_levels(candles))
    return levels, classify_liquidity_events(candles, levels, break_buffer=break_buffer)
