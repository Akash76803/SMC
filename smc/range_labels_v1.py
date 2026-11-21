"""Post-session label computation for Range Predictor V2.

Strictly non-leaky label generation computed ONLY after session close (15:15 IST).
Enforces high/low asymmetry: future excursion targets are evaluated strictly on
bars subsequent to the as-of snapshot time.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time as dtime
from typing import Sequence
from zoneinfo import ZoneInfo

from .models import Candle

IST = ZoneInfo("Asia/Kolkata")
OPEN_TIME = dtime(9, 16)
CLOSE_TIME = dtime(15, 15)
CUTOFF_0916 = dtime(9, 16)
CUTOFF_0930 = dtime(9, 30)


@dataclass(frozen=True)
class DailyRangeLabels:
    """Ground truth session targets evaluated after regular 360-bar session close."""
    date: str
    as_of: str
    spot_at_asof: float
    session_high: float
    session_low: float
    daily_total_range: float
    future_upside: float
    future_downside: float
    upper_barrier_touch: int | None
    lower_barrier_touch: int | None
    expansion_day: int
    upper_barrier_tested: float | None = None
    lower_barrier_tested: float | None = None
    expansion_threshold_tested: float | None = None


def compute_session_labels(
    regular_bars: Sequence[Candle],
    as_of: str,
    spot_at_asof: float,
    upper_barrier: float | None = None,
    lower_barrier: float | None = None,
    expansion_threshold: float | None = None,
) -> DailyRangeLabels:
    """Compute verified session ground truth labels.
    
    Args:
        regular_bars: 360 one-minute bars for the regular session (09:16 to 15:15 IST).
        as_of: Snapshot time ('09:16' or '09:30').
        spot_at_asof: Close price at the snapshot time.
        upper_barrier: Candidate upper price barrier (e.g. spot + expected move).
        lower_barrier: Candidate lower price barrier (e.g. spot - expected move).
        expansion_threshold: Points threshold above which the day is labeled expansion.
    """
    if not regular_bars:
        raise ValueError("Cannot compute session labels from empty regular bars")
    
    date_str = regular_bars[0].timestamp.astimezone(IST).date().isoformat()
    session_high = max(b.high for b in regular_bars)
    session_low = min(b.low for b in regular_bars)
    daily_total_range = round(session_high - session_low, 2)
    
    # Filter bars strictly AFTER the as_of snapshot time
    if as_of == "09:16":
        future_bars = [b for b in regular_bars if b.timestamp.astimezone(IST).time() > CUTOFF_0916]
    elif as_of == "09:30":
        future_bars = [b for b in regular_bars if b.timestamp.astimezone(IST).time() > CUTOFF_0930]
    else:
        raise ValueError(f"Unsupported as_of: {as_of}. Must be '09:16' or '09:30'")
    
    if future_bars:
        max_future_high = max(b.high for b in future_bars)
        min_future_low = min(b.low for b in future_bars)
        future_upside = round(max(0.0, max_future_high - spot_at_asof), 2)
        future_downside = round(max(0.0, spot_at_asof - min_future_low), 2)
        
        upper_touch = 1 if (upper_barrier is not None and max_future_high >= upper_barrier) else 0
        lower_touch = 1 if (lower_barrier is not None and min_future_low <= lower_barrier) else 0
    else:
        future_upside = 0.0
        future_downside = 0.0
        upper_touch = 0 if upper_barrier is not None else None
        lower_touch = 0 if lower_barrier is not None else None
    
    # Expansion label: full session range > threshold
    if expansion_threshold is not None:
        expansion_day = 1 if daily_total_range >= expansion_threshold else 0
    else:
        expansion_day = 0
    
    return DailyRangeLabels(
        date=date_str,
        as_of=as_of,
        spot_at_asof=round(spot_at_asof, 2),
        session_high=round(session_high, 2),
        session_low=round(session_low, 2),
        daily_total_range=daily_total_range,
        future_upside=future_upside,
        future_downside=future_downside,
        upper_barrier_touch=upper_touch if upper_barrier is not None else None,
        lower_barrier_touch=lower_touch if lower_barrier is not None else None,
        expansion_day=expansion_day,
        upper_barrier_tested=upper_barrier,
        lower_barrier_tested=lower_barrier,
        expansion_threshold_tested=expansion_threshold,
    )
