"""V3.3: conservative higher-timeframe structure, dealing ranges and bias.

Inputs must be *already aggregated* complete Monthly/Weekly/Daily OHLC bars
with timestamps at their actual candle CLOSE. Broker HTF START timestamps must
be converted upstream; never guess session durations or holiday calendars.

Research-only: confirmed external BOS/CHoCH is a bias proxy, not a forecast.
No automatic POI, liquidity target, option fill or trade authorization.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .decision_v3 import CheckState
from .engine import confirmed_pivots
from .models import Candle
from .setup_confirmation_v3 import ObservedStage
from .structure_v2 import detect_structure


TIMEFRAMES = ("MONTHLY", "WEEKLY", "DAILY")


class Bias(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class Alignment(str, Enum):
    ALIGNED_BULLISH = "ALIGNED_BULLISH"
    ALIGNED_BEARISH = "ALIGNED_BEARISH"
    CONFLICT = "CONFLICT"
    UNVERIFIED = "UNVERIFIED"


@dataclass(frozen=True)
class DealingRange:
    low: float
    high: float
    equilibrium: float
    position: str
    low_pivot_index: int
    high_pivot_index: int
    available_at: datetime


@dataclass(frozen=True)
class HTFFrame:
    timeframe: str
    bias: Bias
    reason: str
    available_at: datetime | None
    event_source: str | None
    dealing_range: DealingRange | None


@dataclass(frozen=True)
class HTFContext:
    frames: tuple[HTFFrame, ...]
    alignment: Alignment
    reason: str
    as_of: datetime

    def as_dict(self) -> dict:
        return {
            "alignment": self.alignment.value,
            "reason": self.reason,
            "as_of": self.as_of.isoformat(),
            "frames": [
                {
                    "timeframe": f.timeframe,
                    "bias": f.bias.value,
                    "reason": f.reason,
                    "available_at": f.available_at.isoformat() if f.available_at else None,
                    "event_source": f.event_source,
                    "dealing_range": None if f.dealing_range is None else {
                        "low": f.dealing_range.low,
                        "high": f.dealing_range.high,
                        "equilibrium": f.dealing_range.equilibrium,
                        "position": f.dealing_range.position,
                        "low_pivot_index": f.dealing_range.low_pivot_index,
                        "high_pivot_index": f.dealing_range.high_pivot_index,
                        "available_at": f.dealing_range.available_at.isoformat(),
                    },
                } for f in self.frames
            ],
            "research_only": True,
        }


def _frame(timeframe: str, candles: list[Candle], as_of: datetime,
           *, pivot_k: int, max_event_age_bars: int) -> HTFFrame:
    if any(a.timestamp >= b.timestamp for a, b in zip(candles, candles[1:])):
        raise ValueError("HTF_CANDLES_NOT_STRICTLY_ORDERED")
    if any(c.timestamp > as_of for c in candles):
        raise ValueError("FUTURE_HTF_CANDLE")
    if any(not c.complete for c in candles):
        raise ValueError("INCOMPLETE_HTF_CANDLE")
    if len(candles) < 2 * pivot_k + 2:
        return HTFFrame(timeframe, Bias.NEUTRAL, "INSUFFICIENT_CONFIRMED_HISTORY",
                        candles[-1].timestamp if candles else None, None, None)

    pivots = confirmed_pivots(candles, k=pivot_k)
    highs = [p for p in pivots if p.kind == "HIGH"]
    lows = [p for p in pivots if p.kind == "LOW"]
    dealing_range = None
    if highs and lows:
        h, l = highs[-1], lows[-1]
        if h.price > l.price:
            mid = (h.price + l.price) / 2
            last = candles[-1].close
            position = "PREMIUM" if last > mid else "DISCOUNT" if last < mid else "EQUILIBRIUM"
            dealing_range = DealingRange(
                l.price, h.price, mid, position, l.index, h.index,
                candles[max(h.confirmed_at, l.confirmed_at)].timestamp)

    # Use the same causal preliminary structure algorithm as the existing engine.
    events = [e for e in detect_structure(
        candles, internal_k=1, external_k=pivot_k)
        if e.tier == "EXTERNAL"]
    if not events:
        return HTFFrame(timeframe, Bias.NEUTRAL, "NO_CONFIRMED_EXTERNAL_BREAK",
                        candles[-1].timestamp, None, dealing_range)
    recent = events[-1]
    if len(candles) - 1 - recent.candle_index > max_event_age_bars:
        return HTFFrame(timeframe, Bias.NEUTRAL, "EXTERNAL_BREAK_TOO_OLD",
                        candles[-1].timestamp, None, dealing_range)
    return HTFFrame(
        timeframe, Bias(recent.direction),
        "CONFIRMED_EXTERNAL_" + recent.kind,
        candles[recent.candle_index].timestamp,
        f"{timeframe.lower()}:external:{recent.candle_index}",
        dealing_range)


def analyze_htf(*, monthly: list[Candle], weekly: list[Candle],
                daily: list[Candle], as_of: datetime,
                pivot_k: int = 2, max_event_age_bars: int = 8) -> HTFContext:
    """Strict unanimous bias. A conflict is not a reversal prediction."""
    if as_of.tzinfo is None:
        raise ValueError("AS_OF_REQUIRES_TIMEZONE")
    if pivot_k < 2 or max_event_age_bars < 0:
        raise ValueError("INVALID_HTF_PARAMETERS")
    frames = tuple(
        _frame(name, data, as_of, pivot_k=pivot_k,
               max_event_age_bars=max_event_age_bars)
        for name, data in zip(TIMEFRAMES, (monthly, weekly, daily)))
    )
    directions = {f.bias for f in frames if f.bias is not Bias.NEUTRAL}
    if any(f.bias is Bias.NEUTRAL for f in frames):
        alignment, reason = Alignment.UNVERIFIED, "ONE_OR_MORE_HTF_BIASES_UNVERIFIED"
    elif len(directions) > 1:
        alignment, reason = Alignment.CONFLICT, "MONTHLY_WEEKLY_DAILY_BIAS_CONFLICT"
    elif directions == {Bias.BULLISH}:
        alignment, reason = Alignment.ALIGNED_BULLISH, "ALL_THREE_HTF_ALIGNED_BULLISH"
    else:
        alignment, reason = Alignment.ALIGNED_BEARISH, "ALL_THREE_HTF_ALIGNED_BEARISH"
    return HTFContext(frames, alignment, reason, as_of)


def bias_stage(context: HTFContext, *, desired_direction: str) -> ObservedStage:
    """Only strict alignment may confirm HTF_BIAS; nothing confirms HTF_POI."""
    if desired_direction not in ("BULLISH", "BEARISH"):
        raise ValueError("INVALID_DESIRED_DIRECTION")
    expected = (Alignment.ALIGNED_BULLISH if desired_direction == "BULLISH"
                else Alignment.ALIGNED_BEARISH)
    if context.alignment != expected:
        return ObservedStage("HTF_BIAS", CheckState.PENDING, context.reason)
    timestamps = [f.available_at for f in context.frames]
    if any(t is None for t in timestamps):
        return ObservedStage("HTF_BIAS", CheckState.PENDING, "HTF_EVIDENCE_MISSING_TIMESTAMP")
    return ObservedStage(
        "HTF_BIAS", CheckState.PASS, context.reason, max(timestamps),
        "htf:confirmed:" + ",".join(f.event_source for f in context.frames))


def adapt_reversal_with_htf(*, symbol: str, candles: list[Candle],
                            monthly: list[Candle], weekly: list[Candle],
                            daily: list[Candle], observed_at: datetime,
                            data_healthy: bool = False,
                            option_data_verified: bool = False):
    """Safe wiring into V3.2: HTF bias only; POI, premiums and quotes stay WAIT."""
    from .evidence_adapter_v3 import adapt_reversal_candles

    # Evaluate the current LTF state without injecting any HTF confirmation.
    preliminary = adapt_reversal_candles(
        symbol=symbol, candles=candles, observed_at=observed_at,
        data_healthy=data_healthy, option_data_verified=False)
    # Time-of-setup rule: never validate a historical sweep using HTF bars
    # that closed AFTER the sweep. Incomplete calendar context stays WAIT.
    context_time = (candles[preliminary.selected_sweep_index].timestamp
                    if preliminary.selected_sweep_index is not None
                    else observed_at)
    context = analyze_htf(
        monthly=[c for c in monthly if c.timestamp <= context_time],
        weekly=[c for c in weekly if c.timestamp <= context_time],
        daily=[c for c in daily if c.timestamp <= context_time],
        as_of=context_time)
    direction = preliminary.selected_direction
    if direction is None:
        direction = ("BEARISH" if context.alignment is Alignment.ALIGNED_BEARISH
                     else "BULLISH")
    verified_htf = (bias_stage(context, desired_direction=direction),)
    report = adapt_reversal_candles(
        symbol=symbol, candles=candles, observed_at=observed_at,
        verified_htf=verified_htf, data_healthy=data_healthy,
        option_data_verified=False)
    return context, report
