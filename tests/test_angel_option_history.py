from datetime import datetime
from tempfile import TemporaryDirectory
from pathlib import Path
from zoneinfo import ZoneInfo
import csv,pytest
from smc.angel_history import HistoryError
from smc.angel_option_history import resolve_option,download_option,export_option_ohlc
IST=ZoneInfo("Asia/Kolkata")
NOW=datetime(2026,11,11,9,15,tzinfo=IST)
MASTER=[{"symbol":"NIFTY26NOV25000CE","exch_seg":"NFO","instrumenttype":"OPTIDX",
         "token":"12345","expiry":"26NOV2026","strike":"2500000"},
        {"symbol":"NIFTY26NOV25000CE","exch_seg":"NSE","instrumenttype":"AMXIDX",
         "token":"999"},
        {"symbol":"NIFTY26NOV25000PE","exch_seg":"NFO","instrumenttype":"OPTIDX",
         "token":"12346"}]
class API:
    def __init__(self,data):self.data=data;self.calls=[]
    def getCandleData(self,args):
        self.calls.append(args)
        return {"status":True,"data":self.data}
def test_exact_nfo_symbol_identity():
    match=resolve_option(MASTER,"nifty26nov25000ce",token="12345")
    assert match["token"]=="12345"
    assert match["strike_master_raw"]=="2500000"
    with pytest.raises(HistoryError):resolve_option(MASTER,"NIFTY26NOV25000CE",token="999")
    with pytest.raises(ValueError):resolve_option(MASTER,"NIFTY26NOV25000XX")
def test_nfo_exchange_and_candle_close_time():
    api=API([["2026-11-11T09:15:00+05:30",99,103,98,100,200]])
    result=download_option(api,token="12345",interval="ONE_MINUTE",start=NOW,end=NOW,
                           pause_seconds=0)
    assert api.calls[0]["exchange"]=="NFO"
    assert api.calls[0]["symboltoken"]=="12345"
    assert result.candles[0].timestamp==datetime(2026,11,11,9,16,tzinfo=IST)
    with TemporaryDirectory() as d:
        p=Path(d)/"option_ohlc.csv"
        export_option_ohlc(result,p,resolve_option(MASTER,"NIFTY26NOV25000CE"))
        row=list(csv.DictReader(p.open()))[0]
        assert row["close"]=="100.0" and row["trading_symbol"]=="NIFTY26NOV25000CE"
        assert "bid" not in row
def test_empty_api_rejected_not_synthesized():
    with pytest.raises(HistoryError,match="NO_CANDLES"):
        download_option(API([]),token="12345",interval="ONE_MINUTE",start=NOW,end=NOW,
                        pause_seconds=0)
