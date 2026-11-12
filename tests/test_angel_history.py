from datetime import datetime,timedelta
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo
import pytest
from smc.angel_history import HistoryError,batches,resolve_token,download_history,export_csv
from smc.csv_data import read_candles_csv
IST=ZoneInfo("Asia/Kolkata")
A=datetime(2026,1,5,9,15,tzinfo=IST)
ROW=["2026-01-05T09:15:00+05:30",25000,25010,24990,25005,100]
class API:
    def __init__(self,responses): self.responses=iter(responses);self.calls=[]
    def getCandleData(self,params):
        self.calls.append(params)
        r=next(self.responses)
        if isinstance(r,Exception):raise r
        return r

def test_token_lookup():
    m=[dict(name="NIFTY",exch_seg="NSE",token="99926000"),
       dict(name="SENSEX",exch_seg="BSE",token="42")]
    assert resolve_token(m,"NIFTY")=="99926000"
    assert resolve_token(m,"SENSEX")=="42"
    with pytest.raises(HistoryError):resolve_token(m+[dict(name="NIFTY",exch_seg="NSE",token="other")],"NIFTY")
def test_batch_window_contiguous():
    w=batches(A,A+timedelta(days=40),"ONE_MINUTE")
    assert len(w)==2 and w[0][1]+timedelta(minutes=1)==w[1][0]
    assert w[-1][1]==A+timedelta(days=40)
    assert len(batches(A,A+timedelta(days=390),"ONE_HOUR"))==1
def test_batch_invalid():
    with pytest.raises(ValueError):batches(A,A-timedelta(days=1),"ONE_MINUTE")
    with pytest.raises(ValueError):batches(A,A,"THREE_MINUTE")
def test_minute_close_time_csv():
    api=API([dict(status=True,data=[ROW])])
    x=download_history(api,symbol="NIFTY",token="99926000",interval="ONE_MINUTE",start=A,end=A)
    assert x.candles[0].timestamp==A+timedelta(minutes=1)
    assert api.calls[0]["exchange"]=="NSE"
    with TemporaryDirectory() as folder:
        path=Path(folder)/"data.csv"
        export_csv(x,path)
        assert read_candles_csv(path)==list(x.candles)
def test_hour_start_time():
    x=download_history(API([dict(status=True,data=[ROW])]),symbol="NIFTY",
                       token="1",interval="ONE_HOUR",start=A,end=A)
    assert x.candles[0].timestamp==A
def test_no_partial_output_on_failure():
    api=API([dict(status=True,data=[ROW]),RuntimeError("SECRET_KEY")])
    with pytest.raises(HistoryError) as e:
        download_history(api,symbol="NIFTY",token="1",interval="ONE_MINUTE",
                         start=A,end=A+timedelta(days=32),pause_seconds=0)
    assert "SECRET_KEY" not in str(e.value)
    assert "WINDOW_2" in str(e.value)
def test_failure_and_empty():
    with pytest.raises(HistoryError,match="API_REJECTED"):
        download_history(API([dict(status=False,data=None)]),symbol="NIFTY",token="1",
                         interval="ONE_HOUR",start=A,end=A)
    with pytest.raises(HistoryError,match="NO_CANDLES"):
        download_history(API([dict(status=True,data=[])]),symbol="NIFTY",token="1",
                         interval="ONE_HOUR",start=A,end=A)
def test_duplicate_conflict_and_timestamp_range():
    with pytest.raises(HistoryError,match="CONFLICTING"):
        download_history(API([dict(status=True,data=[ROW,ROW[:-1]+[999]])]),
                         symbol="NIFTY",token="1",interval="ONE_MINUTE",start=A,end=A)
    with pytest.raises(HistoryError,match="OUT_OF_RANGE"):
        download_history(API([dict(status=True,data=[ROW])]),symbol="NIFTY",
                         token="1",interval="ONE_MINUTE",start=A+timedelta(days=1),
                         end=A+timedelta(days=1))
