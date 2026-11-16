"""V3.8 closed-timeframe aggregation with strict source coverage.

Only a verified regular 09:16..15:15 Asia/Kolkata 1-minute session may be
aggregated. No incomplete 1H tail is turned into a full hourly candle.
Weekly/monthly completion needs an independently verified trading calendar;
a single observed day or the latest date is never enough proof.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .data_quality import audit_1m
from .models import Candle

IST = ZoneInfo("Asia/Kolkata")
START = time(9, 16)
END = time(15, 15)
REGULAR_MINUTES = 360


@dataclass(frozen=True)
class HTFAggregation:
    bars_5m: tuple[Candle, ...]
    bars_15m: tuple[Candle, ...]
    bars_1h: tuple[Candle, ...]
    daily: tuple[Candle, ...]
    weekly: tuple[Candle, ...]
    monthly: tuple[Candle, ...]
    regular_sessions: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "bars_5m": len(self.bars_5m),
            "bars_15m": len(self.bars_15m),
            "bars_1h": len(self.bars_1h),
            "daily": len(self.daily),
            "weekly": len(self.weekly),
            "monthly": len(self.monthly),
            "regular_sessions": list(self.regular_sessions),
            "htf_bar_timestamps_are_close": True,
            "research_only": True,
        }


def _merge(group: list[Candle]) -> Candle:
    return Candle(
        timestamp=group[-1].timestamp,
        open=group[0].open,
        high=max(c.high for c in group),
        low=min(c.low for c in group),
        close=group[-1].close,
        volume=sum(c.volume for c in group),
        complete=True,
    )


def _fixed(groups: list[list[Candle]], n: int) -> tuple[Candle, ...]:
    return tuple(
        _merge(session[start:start+n])
        for session in groups
        for start in range(0, len(session), n)
        if len(session[start:start+n]) == n
    )


def aggregate_regular_1m(
    candles: list[Candle],
    *,
    verified_week_ends: frozenset[str] = frozenset(),
    verified_month_ends: frozenset[str] = frozenset(),
) -> HTFAggregation:
    """Aggregate complete normal sessions; refuse to invent period endings.

    Weekly/monthly end markers are explicit session dates supplied by an
    independent calendar verifier. Every trading day in their interval must
    be included in the supplied source; this function cannot prove missing
    holidays/days, so callers must not set markers from OHLC alone.
    """
    if not candles:
        raise ValueError("NO_1M_SOURCE")
    if any(not c.complete for c in candles):
        raise ValueError("INCOMPLETE_1M_SOURCE")
    quality = audit_1m(candles)
    if not quality.safe_for_replay:
        raise ValueError("LTF_QUALITY_GATE_FAILED")
    sessions: list[list[Candle]] = []
    for c in candles:
        dt = c.timestamp.astimezone(IST)
        if not sessions or sessions[-1][0].timestamp.astimezone(IST).date() != dt.date():
            sessions.append([])
        sessions[-1].append(c)
    for session in sessions:
        first, last = session[0].timestamp.astimezone(IST), session[-1].timestamp.astimezone(IST)
        if (len(session) != REGULAR_MINUTES or
                first.time() != START or last.time() != END):
            raise ValueError("INCOMPLETE_REGULAR_SESSION")
    dates = tuple(str(s[0].timestamp.astimezone(IST).date()) for s in sessions)
    if not verified_week_ends.issubset(set(dates)) or not verified_month_ends.issubset(set(dates)):
        raise ValueError("UNOBSERVED_CALENDAR_PERIOD_END")
    daily = tuple(_merge(s) for s in sessions)
    weekly: list[Candle] = []
    monthly: list[Candle] = []
    pending_week: list[Candle] = []
    pending_month: list[Candle] = []
    for day, date in zip(daily, dates):
        pending_week.append(day)
        pending_month.append(day)
        if date in verified_week_ends:
            weekly.append(_merge(pending_week))
            pending_week = []
        if date in verified_month_ends:
            monthly.append(_merge(pending_month))
            pending_month = []
    # Omit residual partial hourly 15:15-15:30 market bucket:
    # 09:16..10:15 -> close 10:15; last full 1H closes 15:15.
    return HTFAggregation(
        _fixed(sessions, 5), _fixed(sessions, 15), _fixed(sessions, 60),
        daily, tuple(weekly), tuple(monthly), dates,
    )
