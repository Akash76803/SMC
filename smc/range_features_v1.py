"""Causal feature engineering for Range Predictor V2.

Strictly non-leaky feature calculations for daily history and opening snapshots.
Consumes only completed historical bars and closed opening candles.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import time as dtime
from typing import Sequence
from zoneinfo import ZoneInfo

from .models import Candle

IST = ZoneInfo("Asia/Kolkata")
OPEN_TIME = dtime(9, 16)
CUTOFF_0930 = dtime(9, 30)


@dataclass(frozen=True)
class DailyBar:
    """Completed regular-session daily bar."""
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def range(self) -> float:
        return max(0.0, self.high - self.low)


@dataclass(frozen=True)
class OpeningFeatures:
    """Intraday opening features computed strictly as-of snapshot time."""
    as_of: str
    spot_at_asof: float
    return_from_prior_close: float
    gap_points: float
    gap_pct: float
    open_15m_high: float | None = None
    open_15m_low: float | None = None
    open_15m_range: float | None = None
    open_range_atr_ratio: float | None = None


def compute_true_range(high: float, low: float, prior_close: float) -> float:
    """Compute true range against prior close: max(H-L, |H-Cp|, |L-Cp|)."""
    return max(high - low, abs(high - prior_close), abs(low - prior_close))


def compute_atr(daily_bars: Sequence[DailyBar], period: int = 14) -> float | None:
    """Compute Average True Range across completed prior days.
    
    Requires at least `period + 1` daily bars since each True Range
    requires the previous day's close.
    Returns None if insufficient history is provided.
    """
    if len(daily_bars) < period + 1:
        return None
    
    # Calculate True Range for the last `period` completed days
    # daily_bars[-1] is the most recent completed day
    tr_values: list[float] = []
    start_idx = len(daily_bars) - period
    for i in range(start_idx, len(daily_bars)):
        curr = daily_bars[i]
        prev = daily_bars[i - 1]
        tr = compute_true_range(curr.high, curr.low, prev.close)
        tr_values.append(tr)
    
    return sum(tr_values) / float(period)


def compute_nr7(daily_bars: Sequence[DailyBar]) -> bool:
    """NR7 Volatility Compression Indicator.
    
    Returns True if the most recently completed day's high-low range
    is the lowest or tied-lowest among the last 7 completed sessions.
    Requires at least 7 completed daily bars.
    """
    if len(daily_bars) < 7:
        return False
    
    ranges = [b.range for b in daily_bars[-7:]]
    latest_range = ranges[-1]
    prior_ranges = ranges[:-1]
    
    # Strict tie-breaking rule: <= min of prior 6 completed sessions
    return latest_range <= min(prior_ranges)


def compute_gap(today_open: float, prior_close: float) -> tuple[float, float]:
    """Calculate absolute opening gap points and percentage."""
    gap_pts = today_open - prior_close
    gap_pct = (gap_pts / prior_close) if prior_close > 0.0 else 0.0
    return gap_pts, gap_pct


def compute_realized_volatility(daily_bars: Sequence[DailyBar], window: int = 5) -> float | None:
    """Annualized daily log-return realized volatility over window completed days."""
    if len(daily_bars) < window + 1:
        return None
    
    # Log returns of the last window days
    returns: list[float] = []
    start_idx = len(daily_bars) - window
    for i in range(start_idx, len(daily_bars)):
        curr_c = daily_bars[i].close
        prev_c = daily_bars[i - 1].close
        if curr_c <= 0.0 or prev_c <= 0.0:
            return None
        returns.append(math.log(curr_c / prev_c))
    
    mean_ret = sum(returns) / float(len(returns))
    variance = sum((r - mean_ret) ** 2 for r in returns) / float(len(returns) - 1)
    daily_std = math.sqrt(variance)
    return daily_std * math.sqrt(252.0)


def extract_opening_features(
    as_of: str,
    intraday_bars: Sequence[Candle],
    prior_close: float,
    atr14: float | None = None,
) -> OpeningFeatures:
    """Extract opening features for 09:16 or 09:30 snapshots.
    
    Strict causality:
    - as_of='09:16': Exactly the first 1m closed bar (09:15-09:16 close timestamp).
    - as_of='09:30': First 15 closed 1m bars (09:16 to 09:30 close timestamps).
    """
    if not intraday_bars:
        raise ValueError("Cannot extract opening features from empty intraday bars")
    
    first_bar = intraday_bars[0]
    today_open = first_bar.open
    gap_pts, gap_pct = compute_gap(today_open, prior_close)
    
    if as_of == "09:16":
        spot = first_bar.close
        ret_from_prior = (spot - prior_close) / prior_close if prior_close > 0.0 else 0.0
        return OpeningFeatures(
            as_of=as_of,
            spot_at_asof=spot,
            return_from_prior_close=ret_from_prior,
            gap_points=gap_pts,
            gap_pct=gap_pct,
        )
    elif as_of == "09:30":
        # First 15 bars: 09:16 through 09:30
        snapshot_bars = [b for b in intraday_bars if b.timestamp.astimezone(IST).time() <= CUTOFF_0930]
        if not snapshot_bars:
            snapshot_bars = list(intraday_bars)
        spot = snapshot_bars[-1].close
        ret_from_prior = (spot - prior_close) / prior_close if prior_close > 0.0 else 0.0
        
        high_15m = max(b.high for b in snapshot_bars)
        low_15m = min(b.low for b in snapshot_bars)
        range_15m = high_15m - low_15m
        atr_ratio = (range_15m / atr14) if (atr14 is not None and atr14 > 0.0) else None
        
        return OpeningFeatures(
            as_of=as_of,
            spot_at_asof=spot,
            return_from_prior_close=ret_from_prior,
            gap_points=gap_pts,
            gap_pct=gap_pct,
            open_15m_high=high_15m,
            open_15m_low=low_15m,
            open_15m_range=range_15m,
            open_range_atr_ratio=atr_ratio,
        )
    else:
        raise ValueError(f"Unsupported snapshot as_of time: {as_of}. Must be '09:16' or '09:30'")
