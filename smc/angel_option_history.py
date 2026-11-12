"""Read-only NFO option OHLC adapter: NEVER transforms OHLC into quotes.

Exact contract identity is mandatory to avoid silently downloading a different
expiry or strike. Reuses SmartAPI's existing authenticated history reader.
"""
from __future__ import annotations
import csv
from pathlib import Path
from .angel_history import HistoryError,download_history,HistoryResult

def resolve_option(master:list[dict],trading_symbol:str,*,token:str|None=None)->dict:
    """Resolve exact NFO OPTIDX tradingsymbol and verify optional token."""
    symbol=trading_symbol.strip().upper()
    if not symbol or not symbol.endswith(("CE","PE")):
        raise ValueError("OPTION_TRADINGSYMBOL_MUST_END_CE_OR_PE")
    matches=[row for row in master
             if str(row.get("exch_seg","")).strip().upper()=="NFO"
             and str(row.get("instrumenttype","")).strip().upper()=="OPTIDX"
             and str(row.get("symbol","")).strip().upper()==symbol
             and str(row.get("token","")).strip()]
    if token is not None:
        matches=[row for row in matches if str(row.get("token","")).strip()==token.strip()]
    if len(matches)!=1:
        raise HistoryError("OPTION_CONTRACT_NOT_FOUND_OR_AMBIGUOUS_IN_MASTER")
    row=matches[0]
    return {"trading_symbol":symbol,"token":str(row["token"]).strip(),
            "expiry":str(row.get("expiry","")).strip(),
            "strike_master_raw":str(row.get("strike","")).strip(),
            "instrument_type":"OPTIDX","exchange":"NFO"}

def download_option(client,*,token:str,interval:str,start,end,pause_seconds:float=0.5,
                    sleep=None)->HistoryResult:
    """Download NFO candles with existing strict window and timestamp checks."""
    if not token or not str(token).strip():raise ValueError("OPTION_TOKEN_REQUIRED")
    # Existing index adapter sets exchange from symbol: use proxy exclusively
    # for changing the exchange passed to getCandleData.
    class NFOClient:
        def getCandleData(self,params):
            safe=dict(params)
            safe["exchange"]="NFO"
            return client.getCandleData(safe)
    from .angel_history import download_history
    opts=dict(symbol="NIFTY",token=token,interval=interval,start=start,end=end,
              pause_seconds=pause_seconds)
    if sleep is not None:opts["sleep"]=sleep
    return download_history(NFOClient(),**opts)

def export_option_ohlc(result:HistoryResult,path:str|Path,identity:dict)->None:
    """Distinct OHLC schema: cannot be mistaken for bid/ask tick data."""
    target=Path(path)
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open("w",encoding="utf-8",newline="") as f:
        writer=csv.writer(f)
        writer.writerow(("timestamp","exchange","trading_symbol","token","expiry",
                         "strike_master_raw","open","high","low","close","volume"))
        for c in result.candles:
            writer.writerow((c.timestamp.isoformat(),"NFO",identity["trading_symbol"],
                             identity["token"],identity["expiry"],
                             identity["strike_master_raw"],
                             c.open,c.high,c.low,c.close,c.volume))
