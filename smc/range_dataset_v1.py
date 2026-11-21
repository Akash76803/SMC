"""As-of daily dataset builder for Range Predictor V2.

Builds immutable feature-label rows for 09:16 and 09:30 snapshot horizons
from audited REGULAR_360 sessions. Strictly prevents lookahead leakage.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import time as dtime
from pathlib import Path
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from .angelfolder_backtest_runner import audit_market_data
from .models import Candle
from .range_features_v1 import (
    DailyBar,
    compute_atr,
    compute_gap,
    compute_nr7,
    compute_realized_volatility,
    extract_opening_features,
)
from .range_labels_v1 import DailyRangeLabels, compute_session_labels

IST = ZoneInfo("Asia/Kolkata")
OPEN_TIME = dtime(9, 16)
CUTOFF_0930 = dtime(9, 30)


@dataclass(frozen=True)
class DatasetRow:
    """Single immutable snapshot observation and realized post-session labels."""
    symbol: str
    trading_date: str
    as_of: str
    session_definition: str
    # Causal Features
    spot_at_asof: float
    prior_close: float
    atr5: float | None
    atr14: float | None
    atr20: float | None
    is_nr7: bool
    gap_points: float
    gap_pct: float
    realized_vol_5: float | None
    return_from_prior_close: float
    open_15m_high: float | None = None
    open_15m_low: float | None = None
    open_15m_range: float | None = None
    open_range_atr_ratio: float | None = None
    # Realized Ground Truth Labels (Post-15:15 Close)
    label_daily_total_range: float = 0.0
    label_session_high: float = 0.0
    label_session_low: float = 0.0
    label_future_upside: float = 0.0
    label_future_downside: float = 0.0
    label_expansion_day: int = 0
    label_upper_barrier_touch: int | None = None
    label_lower_barrier_touch: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_daily_bars(usable_sessions: dict[str, list[Candle]]) -> list[DailyBar]:
    """Aggregate regular 360-bar sessions into completed daily bars."""
    daily_bars: list[DailyBar] = []
    sorted_dates = sorted(usable_sessions.keys())
    for d in sorted_dates:
        bars = usable_sessions[d]
        d_bar = DailyBar(
            date=d,
            open=bars[0].open,
            high=max(b.high for b in bars),
            low=min(b.low for b in bars),
            close=bars[-1].close,
            volume=sum(b.volume for b in bars),
        )
        daily_bars.append(d_bar)
    return daily_bars


def generate_range_dataset(
    symbol: str,
    usable_sessions: dict[str, list[Candle]],
    min_history_days: int = 15,
    expansion_factor: float = 1.25,
) -> list[DatasetRow]:
    """Build paired feature-label dataset for 09:16 and 09:30 snapshots.
    
    Args:
        symbol: Market symbol ('NIFTY' or 'SENSEX').
        usable_sessions: Audited dictionary of date -> 360 Candle bars.
        min_history_days: Minimum prior days required for ATR14/NR7.
        expansion_factor: Multiplier over ATR14 for labeling expansion days.
    """
    sorted_dates = sorted(usable_sessions.keys())
    daily_bars = build_daily_bars(usable_sessions)
    date_to_idx = {b.date: i for i, b in enumerate(daily_bars)}
    
    rows: list[DatasetRow] = []
    
    for d_idx, date_str in enumerate(sorted_dates):
        if d_idx < min_history_days:
            # Skip until we have enough completed daily history for ATR14/NR7
            continue
            
        prior_daily = daily_bars[:d_idx]
        session_bars = usable_sessions[date_str]
        prior_close = prior_daily[-1].close
        
        # Daily history features
        atr5 = compute_atr(prior_daily, period=5)
        atr14 = compute_atr(prior_daily, period=14)
        atr20 = compute_atr(prior_daily, period=20)
        is_nr7 = compute_nr7(prior_daily)
        rvol5 = compute_realized_volatility(prior_daily, window=5)
        
        exp_threshold = (expansion_factor * atr14) if atr14 else None
        
        # Build 09:16 Snapshot Row
        open_feat_0916 = extract_opening_features("09:16", session_bars, prior_close, atr14)
        candidate_upper_0916 = (open_feat_0916.spot_at_asof + atr14) if atr14 else None
        candidate_lower_0916 = (open_feat_0916.spot_at_asof - atr14) if atr14 else None
        labels_0916 = compute_session_labels(
            session_bars,
            as_of="09:16",
            spot_at_asof=open_feat_0916.spot_at_asof,
            upper_barrier=candidate_upper_0916,
            lower_barrier=candidate_lower_0916,
            expansion_threshold=exp_threshold,
        )
        row_0916 = DatasetRow(
            symbol=symbol,
            trading_date=date_str,
            as_of="09:16",
            session_definition="REGULAR_360",
            spot_at_asof=open_feat_0916.spot_at_asof,
            prior_close=prior_close,
            atr5=round(atr5, 2) if atr5 else None,
            atr14=round(atr14, 2) if atr14 else None,
            atr20=round(atr20, 2) if atr20 else None,
            is_nr7=is_nr7,
            gap_points=round(open_feat_0916.gap_points, 2),
            gap_pct=round(open_feat_0916.gap_pct, 4),
            realized_vol_5=round(rvol5, 4) if rvol5 else None,
            return_from_prior_close=round(open_feat_0916.return_from_prior_close, 4),
            label_daily_total_range=labels_0916.daily_total_range,
            label_session_high=labels_0916.session_high,
            label_session_low=labels_0916.session_low,
            label_future_upside=labels_0916.future_upside,
            label_future_downside=labels_0916.future_downside,
            label_expansion_day=labels_0916.expansion_day,
            label_upper_barrier_touch=labels_0916.upper_barrier_touch,
            label_lower_barrier_touch=labels_0916.lower_barrier_touch,
        )
        rows.append(row_0916)
        
        # Build 09:30 Snapshot Row
        open_feat_0930 = extract_opening_features("09:30", session_bars, prior_close, atr14)
        candidate_upper_0930 = (open_feat_0930.spot_at_asof + atr14) if atr14 else None
        candidate_lower_0930 = (open_feat_0930.spot_at_asof - atr14) if atr14 else None
        labels_0930 = compute_session_labels(
            session_bars,
            as_of="09:30",
            spot_at_asof=open_feat_0930.spot_at_asof,
            upper_barrier=candidate_upper_0930,
            lower_barrier=candidate_lower_0930,
            expansion_threshold=exp_threshold,
        )
        row_0930 = DatasetRow(
            symbol=symbol,
            trading_date=date_str,
            as_of="09:30",
            session_definition="REGULAR_360",
            spot_at_asof=open_feat_0930.spot_at_asof,
            prior_close=prior_close,
            atr5=round(atr5, 2) if atr5 else None,
            atr14=round(atr14, 2) if atr14 else None,
            atr20=round(atr20, 2) if atr20 else None,
            is_nr7=is_nr7,
            gap_points=round(open_feat_0930.gap_points, 2),
            gap_pct=round(open_feat_0930.gap_pct, 4),
            realized_vol_5=round(rvol5, 4) if rvol5 else None,
            return_from_prior_close=round(open_feat_0930.return_from_prior_close, 4),
            open_15m_high=round(open_feat_0930.open_15m_high, 2) if open_feat_0930.open_15m_high else None,
            open_15m_low=round(open_feat_0930.open_15m_low, 2) if open_feat_0930.open_15m_low else None,
            open_15m_range=round(open_feat_0930.open_15m_range, 2) if open_feat_0930.open_15m_range else None,
            open_range_atr_ratio=round(open_feat_0930.open_range_atr_ratio, 3) if open_feat_0930.open_range_atr_ratio else None,
            label_daily_total_range=labels_0930.daily_total_range,
            label_session_high=labels_0930.session_high,
            label_session_low=labels_0930.session_low,
            label_future_upside=labels_0930.future_upside,
            label_future_downside=labels_0930.future_downside,
            label_expansion_day=labels_0930.expansion_day,
            label_upper_barrier_touch=labels_0930.upper_barrier_touch,
            label_lower_barrier_touch=labels_0930.lower_barrier_touch,
        )
        rows.append(row_0930)
        
    return rows
