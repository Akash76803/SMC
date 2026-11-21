"""SMC Structure and Range Forecast Confluence Engine (Phase P6).

Research-only decision layer:
- Provides context annotations:
  - RANGE_CONTEXT_SUPPORTIVE
  - RANGE_CONTEXT_NEUTRAL
  - RANGE_CONTEXT_CONFLICTING
  - RANGE_CONTEXT_UNAVAILABLE

Protected Constraints:
- Feature flag RANGE_SMC_CONFLUENCE_ENABLED = False by default.
- Zero change to existing minimum 1:2 R:R constraint.
- Never automatically force 1:3 R:R or override SMC structural invalidation.
- Defaults to existing SMC signal engine if range forecast is uncertain.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .range_predictor_v1 import RangeForecast

RANGE_SMC_CONFLUENCE_ENABLED = False


@dataclass
class RangeConfluenceAnnotation:
    """Research annotation evaluating SMC structural setup against expected daily range."""
    status: str
    symbol: str
    setup_direction: str  # 'BULLISH' or 'BEARISH'
    planned_target_points: float
    planned_rr: float
    daily_range_q50: float | None
    daily_range_q90: float | None
    realized_range_so_far: float | None
    range_room_remaining: float | None
    is_target_within_room: bool
    exhaustion_risk: bool
    annotation_reason: str
    confluence_enabled: bool = RANGE_SMC_CONFLUENCE_ENABLED

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_range_confluence(
    symbol: str,
    setup_direction: str,
    planned_target_points: float,
    planned_rr: float,
    forecast: RangeForecast | dict[str, Any] | None,
    current_spot: float,
    session_high: float,
    session_low: float,
    trap_label: str | None = None,
    market_regime: str | None = None,
) -> RangeConfluenceAnnotation:
    """Evaluate whether Range Forecast supports or conflicts with an SMC structural setup.
    
    Strictly advisory research annotation. Never generates or modifies live orders.
    """
    if forecast is None:
        return RangeConfluenceAnnotation(
            status="RANGE_CONTEXT_UNAVAILABLE",
            symbol=symbol,
            setup_direction=setup_direction,
            planned_target_points=planned_target_points,
            planned_rr=planned_rr,
            daily_range_q50=None,
            daily_range_q90=None,
            realized_range_so_far=round(session_high - session_low, 2),
            range_room_remaining=None,
            is_target_within_room=True,
            exhaustion_risk=False,
            annotation_reason="No range forecast available; defaulting to pure SMC structure.",
        )
        
    f_dict = forecast.to_dict() if isinstance(forecast, RangeForecast) else forecast
    f_data = f_dict.get("forecast", {})
    q50 = f_data.get("daily_total_range_q50")
    q90 = f_data.get("daily_total_range_q90")
    
    if q50 is None or q90 is None:
        return RangeConfluenceAnnotation(
            status="RANGE_CONTEXT_UNAVAILABLE",
            symbol=symbol,
            setup_direction=setup_direction,
            planned_target_points=planned_target_points,
            planned_rr=planned_rr,
            daily_range_q50=None,
            daily_range_q90=None,
            realized_range_so_far=round(session_high - session_low, 2),
            range_room_remaining=None,
            is_target_within_room=True,
            exhaustion_risk=False,
            annotation_reason="Forecast quantiles unavailable.",
        )
        
    realized_range = round(session_high - session_low, 2)
    room_to_q90 = max(0.0, round(q90 - realized_range, 2))
    
    # Check exhaustion: if market already consumed > 90% of Q90
    exhaustion_risk = realized_range >= (0.90 * q90)
    
    # Check target room
    is_target_within_room = planned_target_points <= (room_to_q90 * 1.10)
    
    # Classify confluence
    if exhaustion_risk and not is_target_within_room:
        status = "RANGE_CONTEXT_CONFLICTING"
        reason = (
            f"Daily range is stretched (Realized {realized_range:.1f} pts >= 90% of Q90 {q90:.1f} pts). "
            f"Planned target ({planned_target_points:.1f} pts) exceeds available daily expansion room ({room_to_q90:.1f} pts)."
        )
    elif not exhaustion_risk and is_target_within_room:
        status = "RANGE_CONTEXT_SUPPORTIVE"
        reason = (
            f"Ample daily room remains ({room_to_q90:.1f} pts to Q90). "
            f"Planned target ({planned_target_points:.1f} pts) is well within expected volatility band."
        )
    else:
        status = "RANGE_CONTEXT_NEUTRAL"
        reason = f"Normal volatility conditions (Realized {realized_range:.1f} pts, Room {room_to_q90:.1f} pts)."
        
    # Contextual check with Trap Detector
    if trap_label and "TRAP" in trap_label.upper():
        if status == "RANGE_CONTEXT_SUPPORTIVE":
            reason += f" High confluence with {trap_label}."
            
    return RangeConfluenceAnnotation(
        status=status,
        symbol=symbol,
        setup_direction=setup_direction,
        planned_target_points=planned_target_points,
        planned_rr=planned_rr,
        daily_range_q50=q50,
        daily_range_q90=q90,
        realized_range_so_far=realized_range,
        range_room_remaining=room_to_q90,
        is_target_within_room=is_target_within_room,
        exhaustion_risk=exhaustion_risk,
        annotation_reason=reason,
    )
