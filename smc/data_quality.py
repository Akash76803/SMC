"""Session-aware LTF continuity audit. Reports observations, not exchange explanations.

The imported 1M data uses close timestamps. Do not interpolate missing
OHLC, and never interpret an isolated closing record as an ordinary 1M bar.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import timedelta
from typing import Sequence
from zoneinfo import ZoneInfo
from .models import Candle

IST=ZoneInfo("Asia/Kolkata")
STEP=timedelta(minutes=1)

@dataclass(frozen=True)
class DataIssue:
    code:str
    before:str
    after:str
    missing:int
    explanation:str

@dataclass(frozen=True)
class DataQuality:
    count:int
    issues:tuple[DataIssue,...]
    days:int
    coverage_by_day:tuple[tuple[str,int],...]

    @property
    def safe_for_replay(self)->bool:
        return not self.issues

def audit_1m(candles:Sequence[Candle])->DataQuality:
    """Find intraday missing minutes, boundaries and bad daily sequencing.

    Overnight/weekend non-trading intervals are excluded, not called missing
    market data. This does not assert exchange holidays or full-day coverage.
    """
    if not candles:raise ValueError("no candles to audit")
    if any(c.timestamp.tzinfo is None or c.timestamp.utcoffset() is None for c in candles):
        raise ValueError("timezone-aware timestamps required")
    if any(candles[i].timestamp>=candles[i+1].timestamp for i in range(len(candles)-1)):
        raise ValueError("timestamps must be strictly increasing")
    grouped={}
    issues=[]
    for c in candles:
        ts=c.timestamp.astimezone(IST)
        day=ts.date().isoformat()
        grouped.setdefault(day,[]).append(ts)
    for day,times in grouped.items():
        # Session boundary: 09:15 start => first close at 09:16.
        # Do not assume all sessions have identical duration (CAS changes).
        if times[0].hour!=9 or times[0].minute!=16:
            issues.append(DataIssue("SESSION_START_UNVERIFIED","",times[0].isoformat(),
                                    0,"Expected first 1M close 09:16 IST; verify session calendar"))
        for a,b in zip(times,times[1:]):
            delta=b-a
            if delta!=STEP:
                missing=max(0,int(delta.total_seconds()//60)-1)
                special=(a.hour,a.minute,b.hour,b.minute)==(15,15,15,30)
                code="TERMINAL_1530_UNCLASSIFIED" if special else "INTRADAY_GAP"
                issues.append(DataIssue(code,a.isoformat(),b.isoformat(),missing,
                    "Isolated 15:30 index record requires separate source verification"
                    if special else "Do not interpolate missing candles"))
    return DataQuality(len(candles),tuple(issues),len(grouped),
        tuple((day,len(times)) for day,times in grouped.items()))

def drop_terminal_1530(candles:Sequence[Candle])->tuple[Candle,...]:
    """Explicit conservative option: remove only the isolated 15:30 record
    immediately after a 15:15 close. Does NOT turn gaps into continuous data.
    """
    result=[]
    for index,c in enumerate(candles):
        t=c.timestamp.astimezone(IST)
        if index>0:
            prev=candles[index-1].timestamp.astimezone(IST)
            if (prev.date()==t.date() and
                    (prev.hour,prev.minute,t.hour,t.minute)==(15,15,15,30)):
                continue
        result.append(c)
    if not result:raise ValueError("no candles remain")
    return tuple(result)
