"""Read-only SmartAPI historical OHLC adapter; timestamps follow SMC CSV contract."""
from __future__ import annotations
import csv
import json
import time
from dataclasses import dataclass
from datetime import datetime,timedelta
from pathlib import Path
from urllib.request import urlopen
from zoneinfo import ZoneInfo
from .models import Candle

IST=ZoneInfo("Asia/Kolkata")
MASTER_URL="https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
INTERVALS={"ONE_MINUTE":(timedelta(minutes=1),29),"ONE_HOUR":(timedelta(hours=1),399)}
INDICES={"NIFTY":("NSE","NIFTY"),"SENSEX":("BSE","SENSEX")}

class HistoryError(RuntimeError):
    """Exception text must never contain API response or credentials."""

@dataclass(frozen=True)
class HistoryResult:
    candles:tuple[Candle,...]
    requests:int
    empty_requests:int

def resolve_token(master:list[dict],symbol:str)->str:
    if symbol not in INDICES: raise ValueError("unknown symbol")
    exchange,name=INDICES[symbol]
    # The instrument master exposes index names in both "name" and
    # "symbol" fields, depending on the record/version. Do not accidentally
    # select a derivative with a similar name or another exchange.
    aliases={"NIFTY":{"NIFTY","NIFTY 50"},"SENSEX":{"SENSEX"}}[symbol]
    matches=[x for x in master
             if str(x.get("exch_seg","")).upper().strip()==exchange
             and (str(x.get("name","")).upper().strip() in aliases
                  or str(x.get("symbol","")).upper().strip() in aliases)
             and str(x.get("token","")).strip()]
    # Prefer index-specific instrument types over duplicate ordinary symbols.
    indices=[x for x in matches
             if str(x.get("instrumenttype","")).upper().strip() in ("AMXIDX","INDEX")]
    if indices:
        matches=indices
    found={str(x["token"]).strip() for x in matches}
    if len(found)!=1: raise HistoryError("INDEX_TOKEN_MISSING_OR_AMBIGUOUS")
    return found.pop()

def load_master(path:str|Path|None=None)->list[dict]:
    try:
        if path is None:
            with urlopen(MASTER_URL,timeout=25) as response: result=json.load(response)
        else:
            with open(path,encoding="utf-8-sig") as f: result=json.load(f)
    except Exception as exc:
        raise HistoryError("MASTER_UNAVAILABLE") from None
    if not isinstance(result,list): raise HistoryError("MASTER_INVALID")
    return result

def batches(start:datetime,end:datetime,interval:str)->list[tuple[datetime,datetime]]:
    if interval not in INTERVALS: raise ValueError("unsupported interval")
    if start.tzinfo is None or end.tzinfo is None: raise ValueError("timezone needed")
    start,end=start.astimezone(IST),end.astimezone(IST)
    if end<start or any((x.second or x.microsecond) for x in (start,end)):
        raise ValueError("invalid minute-aligned date interval")
    out=[]
    while start<=end:
        limit=min(end,start+timedelta(days=INTERVALS[interval][1]))
        out.append((start,limit))
        start=limit+timedelta(minutes=1)
    return out

def parse_candle(raw,interval:str)->Candle:
    try:
        if len(raw)<6: raise ValueError()
        t=datetime.fromisoformat(str(raw[0]))
        if t.tzinfo is None or t.utcoffset() is None: raise ValueError()
        t=t.astimezone(IST)
        if interval=="ONE_MINUTE": t+=timedelta(minutes=1) # CLOSE-time
        return Candle(t,*(float(v) for v in raw[1:5]),volume=float(raw[5]))
    except (ValueError,TypeError,IndexError) as exc:
        raise HistoryError("INVALID_CANDLE") from None

def download_history(client,*,symbol:str,token:str,interval:str,
                     start:datetime,end:datetime,pause_seconds:float=0.5,
                     sleep=time.sleep)->HistoryResult:
    if symbol not in INDICES or not token or not token.strip() or pause_seconds<0:
        raise ValueError("invalid download configuration")
    windows=batches(start,end,interval)
    data={}
    empty=0
    for i,(a,b) in enumerate(windows):
        params={"exchange":INDICES[symbol][0],"symboltoken":token.strip(),
                "interval":interval,"fromdate":a.strftime("%Y-%m-%d %H:%M"),
                "todate":b.strftime("%Y-%m-%d %H:%M")}
        try: response=client.getCandleData(params)
        except Exception: raise HistoryError(f"REQUEST_FAILED_WINDOW_{i+1}") from None
        if not isinstance(response,dict) or response.get("status") is not True or not isinstance(response.get("data"),list):
            raise HistoryError(f"API_REJECTED_WINDOW_{i+1}")
        if not response["data"]: empty+=1
        for record in response["data"]:
            c=parse_candle(record,interval)
            origin=c.timestamp-timedelta(minutes=1) if interval=="ONE_MINUTE" else c.timestamp
            if origin<a or origin>b: raise HistoryError("OUT_OF_RANGE_CANDLE")
            if c.timestamp in data and data[c.timestamp]!=c:
                raise HistoryError("CONFLICTING_DUPLICATE_CANDLE")
            data[c.timestamp]=c
        if i<len(windows)-1 and pause_seconds: sleep(pause_seconds)
    if not data: raise HistoryError("NO_CANDLES_RETURNED")
    return HistoryResult(tuple(data[t] for t in sorted(data)),len(windows),empty)

def export_csv(result:HistoryResult,path:str|Path)->None:
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open("w",encoding="utf-8",newline="") as f:
        writer=csv.writer(f)
        writer.writerow(("timestamp","open","high","low","close","volume"))
        for c in result.candles:
            writer.writerow((c.timestamp.isoformat(),c.open,c.high,c.low,c.close,c.volume))
