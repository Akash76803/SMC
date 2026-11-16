"""V3.9B continuation validation: trend gate, protective stop proxy and target room.

All decisions are historical research only. OHLC cannot prove exchange stop
liquidity, fills, HTF POI, live option quotes or institutional order flow.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from .continuation_v3 import ContinuationObservation
from .htf_context_v3 import Alignment, HTFContext
from .liquidity import LiquidityEvent, LiquidityLevel
from .models import Candle
from .poi_liquidity_v3 import TargetReview, review_liquidity_target


@dataclass(frozen=True)
class ContinuationValidation:
    status: str
    reason: str
    direction: str
    confirmed_at: str
    htf_alignment: str
    htf_reason: str
    entry_reference: float
    stop_reference: float | None
    risk_points: float | None
    target_level: float | None
    target_points: float | None
    index_rr: float | None
    target_reason: str
    pending_stages: tuple[str, ...]
    research_only: bool = True

    def as_dict(self) -> dict:
        return {
            "status": self.status, "reason": self.reason,
            "direction": self.direction,
            "confirmed_at": self.confirmed_at,
            "htf_alignment": self.htf_alignment,
            "htf_reason": self.htf_reason,
            "entry_reference": self.entry_reference,
            "stop_reference": self.stop_reference,
            "risk_points": self.risk_points,
            "target_level": self.target_level,
            "target_points": self.target_points,
            "index_rr": self.index_rr,
            "target_reason": self.target_reason,
            "pending_stages": list(self.pending_stages),
            "index_bracket": None,  # Never promote a proxy to a verified trade.
            "live_orders_enabled": False,
            "research_only": True,
        }


def validate_continuation(
    *, symbol: str, candles: list[Candle],
    observation: ContinuationObservation, context: HTFContext,
    levels: list[LiquidityLevel], events: list[LiquidityEvent],
    stop_buffer: float = 0.0,
) -> ContinuationValidation:
    """Evaluate only historical evidence available by confirmation close.

    Reconstructs target review from the prefix, never retroactively from
    levels/events that appeared after confirmation. A pullback extreme is
    only a *reference* stop, not a verified protected swing.
    """
    if symbol not in ("NIFTY", "SENSEX") or not isfinite(stop_buffer) or stop_buffer < 0:
        raise ValueError("INVALID_CONTINUATION_VALIDATION_CONFIG")
    if not candles or any(not c.complete for c in candles):
        raise ValueError("INCOMPLETE_CONTINUATION_INPUT")
    if any(a.timestamp >= b.timestamp for a, b in zip(candles, candles[1:])):
        raise ValueError("UNORDERED_CONTINUATION_INPUT")
    if len({c.timestamp.date() for c in candles}) > 1:
        raise ValueError("CROSS_SESSION_CONTINUATION_INPUT")
    ci, pi, bi = (observation.confirm_index, observation.pullback_index,
                  observation.bos_index)
    if not (0 <= bi < pi < ci < len(candles)):
        raise ValueError("INVALID_CONTINUATION_EVENT_INDICES")
    if observation.direction not in ("BULLISH", "BEARISH"):
        raise ValueError("INVALID_CONTINUATION_DIRECTION")
    if context.as_of > candles[ci].timestamp:
        raise ValueError("FUTURE_HTF_CONTEXT")
    if any(frame.available_at is not None and frame.available_at > candles[ci].timestamp
           for frame in context.frames):
        raise ValueError("FUTURE_HTF_FRAME")
    bullish = observation.direction == "BULLISH"
    entry = candles[ci].close
    pullback = candles[pi]
    stop = pullback.low - stop_buffer if bullish else pullback.high + stop_buffer
    expected = Alignment.ALIGNED_BULLISH if bullish else Alignment.ALIGNED_BEARISH
    aligned = context.alignment is expected
    pending = ["PROTECTED_STRUCTURE", "HTF_POI", "OPTION_QUOTES_GREEKS"]
    if not aligned:
        pending.insert(0, "VERIFIED_HTF_BIAS")
    risk = abs(entry - stop) if (stop < entry if bullish else stop > entry) else None
    target: TargetReview | None = None
    if risk is not None:
        # Discard future levels and events; the reviewer additionally checks
        # every eligible pool against observed candle contacts.
        prefix = candles[:ci+1]
        visible_levels = [level for level in levels
                          if 0 <= level.created_at <= ci
                          and level.eligible_from <= ci]
        visible_events = [event for event in events
                          if 0 <= event.candle_index <= ci]
        target = review_liquidity_target(
            candles=prefix, levels=visible_levels, events=visible_events,
            direction=observation.direction, entry=entry, stop=stop,
            symbol=symbol, as_of=prefix[-1].timestamp)
    t = target.target if target is not None else None
    if risk is None:
        status, reason = "NO_TRADE", "INVALID_PULLBACK_STOP_REFERENCE"
        pending.append("VALID_STOP")
    elif target is None or target.status == "WAIT":
        status, reason = "WAIT", "LIQUIDITY_TARGET_UNVERIFIED"
        pending.append("LIQUIDITY_TARGET")
    elif target.status == "NO_TRADE":
        status, reason = "NO_TRADE", target.reason
        pending.append("LIQUIDITY_TARGET_ROOM")
    else:
        status, reason = "WAIT", ("HTF_BIAS_UNVERIFIED" if not aligned
                                  else "PROTECTED_POI_OPTION_EVIDENCE_PENDING")
    return ContinuationValidation(
        status, reason, observation.direction, candles[ci].timestamp.isoformat(),
        context.alignment.value, context.reason, entry,
        stop if risk is not None else None, risk,
        t.price if t else None, t.index_points if t else None,
        t.index_rr if t else None,
        target.reason if target else "NO_VALID_REFERENCE_STOP",
        tuple(pending),
    )
