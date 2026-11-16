"""V3.9 opt-in continuation *research* observations.

A directional BOS, subsequent counter-directional pullback, then a closed-bar
reclaim of the pullback extreme. Purely provisional structural evidence:
no verified HTF alignment, protected POI, liquidity target, or option quote.
This deliberately NEVER emits tradable index brackets or BUY/SELL signals.
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import Candle
from .structure_v2 import detect_structure


@dataclass(frozen=True)
class ContinuationObservation:
    direction: str
    bos_index: int
    pullback_index: int
    confirm_index: int
    broken_level: float
    pullback_extreme: float
    confirmation_close: float
    status: str = "WAIT"
    reason: str = "CONTINUATION_HTF_POI_TARGET_UNVERIFIED"

    def as_dict(self, candles: list[Candle]) -> dict:
        return {
            "timestamp": candles[self.confirm_index].timestamp.isoformat(),
            "direction": self.direction,
            "status": self.status,
            "reason": self.reason,
            "terminal_cause": "PROVISIONAL_BOS_PULLBACK_RECLAIM",
            "source": "CONTINUATION_RESEARCH",
            "diagnostics": {
                "bos_time": candles[self.bos_index].timestamp.isoformat(),
                "pullback_time": candles[self.pullback_index].timestamp.isoformat(),
                "broken_level": self.broken_level,
                "pullback_extreme": self.pullback_extreme,
                "confirmation_close": self.confirmation_close,
                "pending_stages": [
                    "VERIFIED_HTF_BIAS", "PROTECTED_STRUCTURE",
                    "HTF_POI", "LIQUIDITY_TARGET", "OPTION_QUOTES_GREEKS",
                ],
            },
            "index_bracket": None,
            "research_only": True,
        }


def detect_continuation_observations(
    candles: list[Candle], *, max_pullback_bars: int = 12,
    max_confirmation_bars: int = 8,
) -> tuple[ContinuationObservation, ...]:
    """Evaluate only closed input candles; never cross a session boundary.

    A preexisting INTERNAL BOS is the provisional direction. First subsequent
    opposite-body candle is the pullback proxy; price must CLOSE beyond that
    candle's high/low after it. Reversal CHoCH cancels the candidate. Confirmed
    events are tied to their *actual* close, not a later hindsight pivot.
    """
    if max_pullback_bars < 1 or max_confirmation_bars < 1:
        raise ValueError("INVALID_CONTINUATION_WINDOWS")
    if any(not c.complete for c in candles):
        raise ValueError("INCOMPLETE_CONTINUATION_CANDLES")
    if any(a.timestamp >= b.timestamp for a, b in zip(candles, candles[1:])):
        raise ValueError("UNORDERED_CONTINUATION_CANDLES")
    if not candles:
        return ()
    if len({c.timestamp.date() for c in candles}) > 1:
        raise ValueError("CONTINUATION_REQUIRES_SINGLE_SESSION")
    events = [e for e in detect_structure(candles) if e.tier == "INTERNAL"]
    bos_events = [e for e in events if e.kind == "BOS"]
    observations = []
    occupied_until = -1
    for bos in bos_events:
        start = bos.candle_index
        if start <= occupied_until:
            continue
        bullish = bos.direction == "BULLISH"
        opposite_event = next(
            (e.candle_index for e in events
             if e.candle_index > start and e.kind == "CHoCH"
             and e.direction != bos.direction), len(candles))
        pullback_index = None
        for j in range(start + 1, min(len(candles), start + max_pullback_bars + 1,
                                       opposite_event)):
            c = candles[j]
            if (c.close < c.open if bullish else c.close > c.open):
                pullback_index = j
                break
        if pullback_index is None:
            continue
        pullback = candles[pullback_index]
        threshold = pullback.high if bullish else pullback.low
        for j in range(pullback_index + 1,
                       min(len(candles), pullback_index + max_confirmation_bars + 1,
                           opposite_event)):
            candle = candles[j]
            # A close through the pullback extreme is a structural *proxy*,
            # not confirmed MSS, FVG, POI, or an assumed order fill.
            reclaim = candle.close > threshold if bullish else candle.close < threshold
            if reclaim:
                observations.append(ContinuationObservation(
                    bos.direction, start, pullback_index, j,
                    bos.broken_pivot.price, threshold, candle.close))
                occupied_until = j
                break
    return tuple(observations)
