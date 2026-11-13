"""Phase 6.3: conservative option OHLC candle research, NOT bid/ask fills.

Exact Angel One option candles: timestamp is one-minute candle CLOSE. An index
signal at T can enter ONLY at the OPEN of the option candle closing T+1min.
STOP wins ambiguous same-bar excursions. No synthetic candles, overnight fills,
or performance claims for missing bars. Results are separately hypothetical per
strategy/contract, not an executable combined portfolio.
"""
from __future__ import annotations
import csv
from collections import Counter
from dataclasses import dataclass
from datetime import datetime,timedelta,time
from pathlib import Path
from zoneinfo import ZoneInfo
from .models import Candle,Side

IST=ZoneInfo("Asia/Kolkata")
LIMIT=time(15,15)

@dataclass(frozen=True)
class OptionSeries:
    trading_symbol:str
    token:str
    expiry_raw:str
    candles:tuple[Candle,...]
    @property
    def side(self):
        return Side.CE if self.trading_symbol.endswith("CE") else Side.PE

@dataclass(frozen=True)
class IndexEvent:
    timestamp:datetime
    symbol:str
    side:Side
    strategy:str

@dataclass(frozen=True)
class OHLCTrade:
    strategy:str
    trading_symbol:str
    signal_time:datetime
    entry_time:datetime
    exit_time:datetime
    entry_open:float
    exit_assumed:float
    target:float
    stop:float
    exit_reason:str
    gross_premium_points:float
    max_favorable_envelope:float
    max_adverse_envelope:float

def read_series(file:str|Path)->OptionSeries:
    candles=[]
    contract=None
    with open(file,encoding="utf-8-sig",newline="") as handle:
        reader=csv.DictReader(handle)
        needed={"timestamp","exchange","trading_symbol","token","expiry",
                "open","high","low","close","volume"}
        if reader.fieldnames is None or not needed.issubset(reader.fieldnames):
            raise ValueError("REQUIRES_EXACT_ANGEL_OPTION_OHLC_SCHEMA")
        for line,row in enumerate(reader,2):
            try:
                identity=(row["trading_symbol"].strip().upper(),
                          row["token"].strip(),row["expiry"].strip())
                if row["exchange"].strip().upper()!="NFO" or not identity[0].endswith(("CE","PE")):
                    raise ValueError("INVALID_OPTION_CONTRACT")
                if contract is None:contract=identity
                if contract!=identity:raise ValueError("MIXED_OPTION_CONTRACTS")
                ts=datetime.fromisoformat(row["timestamp"])
                c=Candle(ts,float(row["open"]),float(row["high"]),float(row["low"]),
                         float(row["close"]),float(row["volume"]))
                if candles and c.timestamp<=candles[-1].timestamp:
                    raise ValueError("UNSORTED_OR_DUPLICATE_CANDLES")
            except (ValueError,TypeError,KeyError) as exc:
                raise ValueError(f"INVALID_OPTION_ROW_{line}: {exc}") from exc
            candles.append(c)
    if not candles:raise ValueError("NO_OPTION_OHLC_CANDLES")
    return OptionSeries(*contract,tuple(candles))

def read_events(path:str|Path)->tuple[IndexEvent,...]:
    events=[]
    with open(path,encoding="utf-8-sig",newline="") as handle:
        reader=csv.DictReader(handle)
        if reader.fieldnames is None or not {"timestamp","symbol","side","strategy"}.issubset(reader.fieldnames):
            raise ValueError("INDEX_SIGNALS_REQUIRED_COLUMNS")
        for line,row in enumerate(reader,2):
            try:
                stamp=datetime.fromisoformat(row["timestamp"])
                if stamp.tzinfo is None:raise ValueError("SIGNAL_TIME_REQUIRES_OFFSET")
                events.append(IndexEvent(stamp,row["symbol"].upper().strip(),
                                         Side(row["side"].upper().strip()),
                                         row["strategy"].strip()))
            except (ValueError,KeyError) as exc:
                raise ValueError(f"INVALID_SIGNAL_ROW_{line}: {exc}") from exc
    return tuple(events)

def simulate(events:tuple[IndexEvent,...],series:OptionSeries,
             *,target_points:float=25.0,stop_points:float=10.0,
             hold_bars:int=24)->tuple[tuple[OHLCTrade,...],dict[str,int]]:
    if target_points<=0 or stop_points<=0 or hold_bars<1:
        raise ValueError("INVALID_RESEARCH_BRACKET")
    quotes=series.candles
    by_timestamp={c.timestamp:c for c in quotes}
    trades=[]
    counts=Counter()
    # Multiple strategy labels at the same instant, side and symbol describe
    # ONE market entry opportunity, not independent fills or P&L.
    grouped={}
    for event in events:
        if event.timestamp.tzinfo is None:
            raise ValueError("SIGNAL_TIME_REQUIRES_OFFSET")
        key=(event.timestamp,event.symbol,event.side)
        grouped.setdefault(key,set()).add(event.strategy)
    counts["DUPLICATE_STRATEGY_LABELS_COLLAPSED"]=len(events)-len(grouped)
    unique_events=(IndexEvent(timestamp,symbol,side,"+".join(sorted(labels)))
                   for (timestamp,symbol,side),labels in sorted(
                       grouped.items(),key=lambda x:x[0][0]))
    for event in unique_events:
        if event.side!=series.side or not series.trading_symbol.startswith(event.symbol):
            counts["SIGNAL_CONTRACT_MISMATCH"]+=1
            continue
        signal_time=event.timestamp.astimezone(IST)
        next_time=signal_time+timedelta(minutes=1)
        # The option candle at next_time represents prices [signal_time,next_time].
        # Its OPEN is the earliest causal OHLC entry proxy.
        if next_time.time()>LIMIT:
            counts["LATE_SIGNAL"]+=1
            continue
        start=by_timestamp.get(next_time)
        if start is None or start.timestamp.astimezone(IST).date()!=signal_time.date():
            counts["NO_CONTIGUOUS_NEXT_OPTION_BAR"]+=1
            continue
        entry=start.open
        target=entry+target_points
        stop=entry-stop_points
        if stop<=0:
            counts["INVALID_STOP"]+=1
            continue
        span=[]
        outcome=None
        for age in range(hold_bars):
            tick=by_timestamp.get(next_time+timedelta(minutes=age))
            if tick is None:
                counts["INTRATRADE_MISSING_CANDLE"]+=1
                break
            local=tick.timestamp.astimezone(IST)
            if local.date()!=signal_time.date() or local.time()>LIMIT:
                counts["SESSION_CUTOFF_NO_EXIT"]+=1
                break
            span.append(tick)
            # Gap open: entry bar open is already known; for subsequent bars
            # use actual open, never an optimistic threshold.
            if age>0 and tick.open<=stop:
                outcome=(tick,tick.open,"STOP_GAP_OPEN")
            elif age>0 and tick.open>=target:
                outcome=(tick,tick.open,"TARGET_GAP_OPEN")
            elif tick.low<=stop:  # both hit? STOP first by policy
                outcome=(tick,stop,"STOP_OHLC")
            elif tick.high>=target:
                outcome=(tick,target,"TARGET_OHLC")
            elif age==hold_bars-1:
                outcome=(tick,tick.close,"TIME_EXIT_OHLC_CLOSE")
            if outcome:break
        if not outcome:
            # Incomplete quote coverage is never allowed to imply profit.
            continue
        last,exit_price,reason=outcome
        mfe=max(0.0,max(c.high for c in span)-entry)
        mae=max(0.0,entry-min(c.low for c in span))
        trades.append(OHLCTrade(event.strategy,series.trading_symbol,
                  signal_time,start.timestamp,last.timestamp,entry,exit_price,
                  target,stop,reason,exit_price-entry,mfe,mae))
    return tuple(trades),dict(sorted(counts.items()))
