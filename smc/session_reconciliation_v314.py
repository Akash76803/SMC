"""Conservative regular-session recovery from Angel 1m index candles.

Known isolated 15:29/15:30 index observations are quarantined only when
preceded by a complete, contiguous 09:16..15:15 360-close regular session.
Partial, duplicate or internally gapped sessions are never repaired.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import time, timedelta
from zoneinfo import ZoneInfo
from .models import Candle

IST = ZoneInfo("Asia/Kolkata")
OPEN = time(9, 16)
CLOSE = time(15, 15)
ISOLATED = {time(15, 29), time(15, 30)}


def reconcile_sessions(candles: list[Candle]) -> tuple[dict[str, list[Candle]], list[dict]]:
    if not candles or any(a.timestamp >= b.timestamp
                          for a, b in zip(candles, candles[1:])):
        raise ValueError("EMPTY_OR_UNORDERED_HISTORICAL_CANDLES")
    grouped: dict[str, list[Candle]] = defaultdict(list)
    for candle in candles:
        at = candle.timestamp.astimezone(IST)
        grouped[at.date().isoformat()].append(candle)
    usable: dict[str, list[Candle]] = {}
    audit: list[dict] = []
    for day, source in grouped.items():
        regular = [c for c in source
                   if OPEN <= c.timestamp.astimezone(IST).time() <= CLOSE]
        extras = [c for c in source
                  if not OPEN <= c.timestamp.astimezone(IST).time() <= CLOSE]
        continuous = (len(regular) == 360
                      and regular[0].timestamp.astimezone(IST).time() == OPEN
                      and regular[-1].timestamp.astimezone(IST).time() == CLOSE
                      and all(b.timestamp-a.timestamp == timedelta(minutes=1)
                              for a, b in zip(regular, regular[1:])))
        # Never silently discard odd out-of-session packets or multiple records.
        recognized = (len(extras) == 0 or
                      len(extras) == 1 and extras[0].timestamp.astimezone(IST).time() in ISOLATED
                      and extras[0].timestamp > regular[-1].timestamp if regular else False)
        if continuous and recognized:
            usable[day] = regular
            status = "RECOVERED_ISOLATED_POST_SESSION" if extras else "COMPLETE"
            reason = "REGULAR_360_CONTIGUOUS"
        else:
            status = "EXCLUDED"
            reason = ("INCOMPLETE_REGULAR_360_BARS" if len(regular) != 360
                      else "INTRADAY_GAP_OR_UNKNOWN_EXTRA")
        audit.append({
            "date": day, "status": status, "reason": reason,
            "raw_bars": len(source), "regular_bars": len(regular),
            "quarantined_timestamps": [x.timestamp.isoformat() for x in extras]
            if status == "RECOVERED_ISOLATED_POST_SESSION" else [],
        })
    return usable, audit
