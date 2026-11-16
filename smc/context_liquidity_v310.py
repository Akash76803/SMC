"""V3.10 liquidity map for prior observed sessions, confirmed weeks and local pivots.

A previously observed day is not automatically the exchange's immediately
preceding trading day. Week-end markers must come from an independently
verified trading calendar; no inference from weekdays or truncated history.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .engine import confirmed_pivots
from .liquidity import LiquidityLevel, liquidity_map
from .models import Candle
from .market_context_v310 import _check

IST = ZoneInfo("Asia/Kolkata")


def contextual_liquidity(*, candles: list[Candle], as_of: datetime,
                         verified_week_ends: frozenset[str] = frozenset(),
                         verified_predecessors: frozenset[str] = frozenset()) -> dict:
    """Map levels visible at as_of; never assert an unverified date was adjacent."""
    if as_of.tzinfo is None:
        raise ValueError("AS_OF_REQUIRES_OFFSET")
    _check(candles)
    seen = [c for c in candles if c.timestamp <= as_of]
    if not seen:
        return {"levels": [], "prior_observed_day": None,
                "completed_week": None, "research_only": True}
    sessions: dict[str, list[Candle]] = {}
    for c in seen:
        day = c.timestamp.astimezone(IST).date().isoformat()
        sessions.setdefault(day, []).append(c)
    days = list(sessions)
    today = days[-1]
    prior = days[-2] if len(days) >= 2 else None
    prior_day = None
    extra: list[LiquidityLevel] = []
    if prior is not None and len(sessions[prior]) == 360:
        prev = sessions[prior]
        high = max(c.high for c in prev)
        low = min(c.low for c in prev)
        verified = today in verified_predecessors
        prior_day = {
            "date": prior, "high": high, "low": low,
            "is_verified_immediate_predecessor": verified,
            "source": "OBSERVED_COMPLETE_SESSION",
        }
        if verified:
            # The current session starts at the first candle in 'seen'
            # belonging to today. Certified prior session levels are eligible
            # immediately at its open, like PDH/PDL.
            curr_idx = len(seen) - len(sessions[today])
            hi_idx = max(range(len(prev)), key=lambda i: prev[i].high)
            lo_idx = min(range(len(prev)), key=lambda i: prev[i].low)
            extra.extend([
                LiquidityLevel("PDH", high, curr_idx, (hi_idx,), curr_idx),
                LiquidityLevel("PDL", low, curr_idx, (lo_idx,), curr_idx),
            ])

    completed_week = None
    # Never create a weekly boundary from the end of supplied CSV. Only an
    # explicitly verified week-end marker may close a historical week.
    eligible_ends = [d for d in days[:-1]
                     if d in verified_week_ends and len(sessions[d]) == 360]
    if eligible_ends:
        last_end = eligible_ends[-1]
        previous_end = next((d for d in reversed(eligible_ends[:-1])), None)
        span = [d for d in days if (previous_end is None or d > previous_end)
                and d <= last_end]
        if span and all(len(sessions[d]) == 360 for d in span):
            points = [c for d in span for c in sessions[d]]
            completed_week = {
                "end_date": last_end,
                "high": max(c.high for c in points),
                "low": min(c.low for c in points),
                "calendar_marker_verified": True,
                "history_completeness_independently_verified": False,
                "research_only": True,
            }
            # Informational only: absent independently verified full-week
            # session coverage, these levels are NOT fed to target gates.

    # Local equal highs/lows and individual confirmed swing pools.
    pivots = confirmed_pivots(seen, k=2)
    local, events = liquidity_map(seen, pivots)
    # liquidity_map's own PDH/PDL inputs rely on prior observed sessions and
    # cannot by themselves prove immediate calendar adjacency.
    local = [l for l in local if l.kind not in ("PDH", "PDL")]
    return {
        "levels": [
            {"kind": l.kind, "price": l.price,
             "eligible_from": l.eligible_from,
             "verified_calendar": l in extra,
             "research_only": True}
            for l in (*local, *extra)
            if l.eligible_from < len(seen)
        ],
        "prior_observed_day": prior_day,
        "completed_week": completed_week,
        "research_only": True,
    }
