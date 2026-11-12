"""Phase 6 paper replay on OBSERVED option bid/ask quotes (never projected P&L)."""
from __future__ import annotations
import csv
from dataclasses import dataclass
from datetime import datetime,timedelta
from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import Side
IST=ZoneInfo("Asia/Kolkata")

@dataclass(frozen=True)
class Quote:
    timestamp:datetime
    symbol:str
    side:Side
    strike:float
    expiry:datetime
    bid:float
    ask:float
    lot_size:int
    volume:int
    delta:float|None=None
    def __post_init__(self):
        if self.timestamp.tzinfo is None or self.expiry.tzinfo is None:
            raise ValueError("QUOTE_TIMESTAMPS_NEED_OFFSET")
        if self.bid<=0 or self.ask<self.bid or self.strike<=0 or self.lot_size<1 or self.volume<0:
            raise ValueError("INVALID_OPTION_QUOTE")
    @property
    def contract(self):
        return self.symbol,self.side,self.strike,self.expiry

@dataclass(frozen=True)
class Signal:
    timestamp:datetime
    symbol:str
    side:Side
    strategy:str

@dataclass(frozen=True)
class Settings:
    target_points:float=25.0
    stop_points:float=10.0
    cost_per_unit:float=1.0
    max_spread_points:float=3.0
    max_spread_fraction:float=0.04
    min_volume:int=1
    max_entry_delay_seconds:int=90
    max_gap_seconds:int=120
    max_holding_minutes:int=24
    def __post_init__(self):
        if not (self.target_points>0 and self.stop_points>0 and self.cost_per_unit>=0
                and self.max_spread_points>=0 and 0<self.max_spread_fraction<=1
                and self.min_volume>=0 and self.max_entry_delay_seconds>=1
                and self.max_gap_seconds>=1 and self.max_holding_minutes>=1):
            raise ValueError("INVALID_PREMIUM_CONFIG")
        if (self.target_points-self.cost_per_unit)/(self.stop_points+self.cost_per_unit)<2:
            raise ValueError("NET_PREMIUM_RR_BELOW_2")

@dataclass(frozen=True)
class Trade:
    strategy:str
    symbol:str
    side:Side
    strike:float
    expiry:datetime
    signal_time:datetime
    entry_time:datetime
    exit_time:datetime
    entry_ask:float
    exit_bid:float
    target_bid:float
    stop_bid:float
    exit_reason:str
    net_per_unit:float
    lot_size:int
    net_one_lot:float

def read_quotes(path:str|Path)->list[Quote]:
    rows=[]
    used=set()
    with open(path,newline="",encoding="utf-8-sig") as f:
        reader=csv.DictReader(f)
        cols={"timestamp","symbol","side","strike","expiry","bid","ask","lot_size","volume"}
        if reader.fieldnames is None or not cols.issubset(reader.fieldnames):
            raise ValueError("QUOTE_CSV_REQUIRED_COLUMNS_MISSING")
        for n,row in enumerate(reader,2):
            try:
                q=Quote(datetime.fromisoformat(row["timestamp"]),
                        row["symbol"].strip().upper(),Side(row["side"].strip().upper()),
                        float(row["strike"]),datetime.fromisoformat(row["expiry"]),
                        float(row["bid"]),float(row["ask"]),int(row["lot_size"]),
                        int(row["volume"]),float(row["delta"]) if row.get("delta") else None)
                key=(q.contract,q.timestamp)
                if key in used:raise ValueError("DUPLICATE_QUOTE")
                used.add(key)
                if rows and q.timestamp<rows[-1].timestamp:
                    raise ValueError("QUOTES_NOT_SORTED")
            except (ValueError,KeyError,TypeError) as ex:
                raise ValueError(f"INVALID_QUOTE_ROW_{n}: {ex}") from ex
            rows.append(q)
    if not rows:raise ValueError("EMPTY_OPTION_QUOTES")
    return rows

def replay(signals:list[Signal],quotes:list[Quote],settings:Settings=Settings()):
    """Conservative quote-time simulation; no lookahead, no overnight exits.

    Entries buy at observed ask; exits sell at observed bid. When there is a
    coverage gap, mark unobservable, NEVER call that trade a winner.
    Independent one-trade-per-day research; no real order routing.
    """
    grouped={}
    for q in quotes:grouped.setdefault(q.contract,[]).append(q)
    for chain in grouped.values():chain.sort(key=lambda x:x.timestamp)
    trades=[]
    skipped=Counter()
    occupied=set()
    for s in sorted(signals,key=lambda x:x.timestamp):
        if s.timestamp.tzinfo is None:raise ValueError("SIGNAL_TIME_NEEDS_OFFSET")
        day=s.timestamp.astimezone(IST).date()
        if day in occupied:
            skipped["ONE_POSITION_PER_DAY"]+=1
            continue
        candidates=[q for q in quotes if q.timestamp>s.timestamp
                    and q.timestamp<=s.timestamp+timedelta(seconds=settings.max_entry_delay_seconds)
                    and q.timestamp.astimezone(IST).date()==day
                    and q.expiry>q.timestamp and q.symbol==s.symbol and q.side==s.side
                    and q.volume>=settings.min_volume
                    and q.ask-q.bid<=settings.max_spread_points
                    and (q.ask-q.bid)/q.ask<=settings.max_spread_fraction]
        if not candidates:
            skipped["NO_FRESH_LIQUID_QUOTE"]+=1
            continue
        earliest=min(q.timestamp for q in candidates)
        entry=min((q for q in candidates if q.timestamp==earliest),
                  key=lambda q:(q.ask-q.bid,-q.volume,q.strike))
        target=entry.ask+settings.target_points
        stop=entry.ask-settings.stop_points
        if stop<=0:
            skipped["INVALID_STOP"]+=1
            continue
        end=entry.timestamp+timedelta(minutes=settings.max_holding_minutes)
        chain=[q for q in grouped[entry.contract] if entry.timestamp<q.timestamp<=end
               and q.timestamp.astimezone(IST).date()==day]
        if not chain:
            skipped["NO_EXIT_TICKS"]+=1
            continue
        prev=entry.timestamp
        outcome=None
        for q in chain:
            if (q.timestamp-prev).total_seconds()>settings.max_gap_seconds:
                skipped["UNOBSERVABLE_QUOTE_GAP"]+=1
                break
            prev=q.timestamp
            if q.bid<=stop:outcome=(q,"STOP_OBSERVED_BID");break
            if q.bid>=target:outcome=(q,"TARGET_OBSERVED_BID");break
            if q.timestamp>=end:outcome=(q,"TIME_EXIT_OBSERVED_BID");break
        else:
            skipped["NO_VERIFIED_EXIT"]+=1
        if outcome is None:continue
        q,reason=outcome
        net=q.bid-entry.ask-settings.cost_per_unit
        trades.append(Trade(s.strategy,s.symbol,s.side,entry.strike,entry.expiry,
                            s.timestamp,entry.timestamp,q.timestamp,entry.ask,
                            q.bid,target,stop,reason,net,entry.lot_size,net*entry.lot_size))
        occupied.add(day)
    return trades,dict(sorted(skipped.items()))
