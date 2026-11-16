"""V3.10 causal multi-timeframe market context, not a trade signal.

Sources are audited 1m close-time candles. 5m/15m/1h bars are created only
from complete contiguous buckets starting at 09:16 IST. Never use partial
candles or a later session's data as evidence at an earlier confirmation.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .engine import confirmed_pivots
from .models import Candle
from .structure_v2 import detect_structure

IST = ZoneInfo("Asia/Kolkata")
FIRST = time(9, 16)
LAST = time(15, 15)


def _check(candles: list[Candle]) -> None:
    if any(not c.complete for c in candles):
        raise ValueError("INCOMPLETE_MTF_SOURCE")
    if any(a.timestamp >= b.timestamp for a, b in zip(candles, candles[1:])):
        raise ValueError("UNORDERED_MTF_SOURCE")
    days: dict[str, list[Candle]] = defaultdict(list)
    for c in candles:
        t = c.timestamp.astimezone(IST)
        if not FIRST <= t.time() <= LAST:
            raise ValueError("OUT_OF_SESSION_MTF_SOURCE")
        days[t.date().isoformat()].append(c)
    for session in days.values():
        if session[0].timestamp.astimezone(IST).time() != FIRST:
            raise ValueError("UNVERIFIED_SESSION_START")
        if len(session) > 360:
            raise ValueError("OVERLONG_MTF_SESSION")
        for a, b in zip(session, session[1:]):
            if b.timestamp - a.timestamp != timedelta(minutes=1):
                raise ValueError("INTRADAY_MTF_GAP")


def _merge(group: list[Candle]) -> Candle:
    return Candle(group[-1].timestamp, group[0].open,
                  max(c.high for c in group), min(c.low for c in group),
                  group[-1].close, sum(c.volume for c in group))


def closed_timeframes(candles: list[Candle], *, as_of: datetime) -> dict[str, list[Candle]]:
    """Only completed 5m/15m/1h buckets; historical complete daily sessions."""
    if as_of.tzinfo is None:
        raise ValueError("AS_OF_REQUIRES_OFFSET")
    _check(candles)
    observed = [c for c in candles if c.timestamp <= as_of]
    by_day: dict[str, list[Candle]] = defaultdict(list)
    for c in observed:
        by_day[c.timestamp.astimezone(IST).date().isoformat()].append(c)
    output = {"5m": [], "15m": [], "1h": [], "daily": []}
    for session in by_day.values():
        for name, n in (("5m", 5), ("15m", 15), ("1h", 60)):
            for j in range(0, len(session), n):
                subset = session[j:j+n]
                if len(subset) == n:
                    output[name].append(_merge(subset))
        if len(session) == 360 and session[-1].timestamp.astimezone(IST).time() == LAST:
            output["daily"].append(_merge(session))
    return output


def structure_snapshot(candles: list[Candle], *, timeframe: str) -> dict:
    """Causal last confirmed structural direction; HH-HL is descriptive."""
    pivots = confirmed_pivots(candles, k=2)
    highs = [p for p in pivots if p.kind == "HIGH"]
    lows = [p for p in pivots if p.kind == "LOW"]
    if len(highs) >= 2 and len(lows) >= 2:
        if highs[-1].price > highs[-2].price and lows[-1].price > lows[-2].price:
            wave = "HH_HL"
        elif highs[-1].price < highs[-2].price and lows[-1].price < lows[-2].price:
            wave = "LH_LL"
        else:
            wave = "MIXED"
    else:
        wave = "UNVERIFIED"
    breaks = detect_structure(candles, internal_k=1, external_k=2) if len(candles) >= 6 else []
    recent = next((e for e in reversed(breaks) if e.tier == "EXTERNAL"), None)
    return {
        "timeframe": timeframe,
        "closed_bars": len(candles),
        "wave_structure": wave,
        "bias": recent.direction if recent else "UNVERIFIED",
        "last_break": recent.kind if recent else None,
        "last_break_at": candles[recent.candle_index].timestamp.isoformat() if recent else None,
        "last_break_level": recent.broken_pivot.price if recent else None,
        "confirmed_high": highs[-1].price if highs else None,
        "confirmed_low": lows[-1].price if lows else None,
        "research_only": True,
    }


def analyze_mtf(candles: list[Candle], *, as_of: datetime,
                direction: str | None = None) -> dict:
    if direction not in ("BULLISH", "BEARISH", None):
        raise ValueError("INVALID_MTF_DIRECTION")
    frames = closed_timeframes(candles, as_of=as_of)
    snapshots = {name: structure_snapshot(frames[name], timeframe=name)
                 for name in ("1h", "15m", "5m")}
    values = [snapshots[name]["bias"] for name in ("1h", "15m", "5m")]
    if "UNVERIFIED" in values:
        alignment = "UNVERIFIED"
    elif len(set(values)) > 1:
        alignment = "CONFLICT"
    else:
        alignment = "ALIGNED_" + values[0]
    desired = "ALIGNED_" + direction if direction else None
    return {
        "as_of": as_of.isoformat(),
        "timeframes": snapshots,
        "daily_closed_bars": len(frames["daily"]),
        "alignment": alignment,
        "direction_match": alignment == desired if desired else None,
        "independent_monthly_weekly_daily_verified": False,
        "research_only": True,
    }
