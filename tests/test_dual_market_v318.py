"""Dual NIFTY/SENSEX browser and alert routing without live brokerage."""
from datetime import datetime, timezone, timedelta
from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.request import urlopen
from urllib.error import HTTPError
import io
import json

import pytest

from smc.angel_dual_stream_v318 import run_dual_stream
from smc.dual_market_v318 import (select_symbol, market_paths,
                                  unavailable_snapshot, get_historical_snapshots)
from smc.app_terminal_v316 import make_handler, live_screen_payload, HTML
from smc.angel_stream_cli_v312 import write_live_status

IST=timezone(timedelta(hours=5,minutes=30))


def test_market_selection_never_falls_back_to_other_symbol(tmp_path):
    assert select_symbol("nifty")=="NIFTY"
    assert select_symbol("Sensex")=="SENSEX"
    assert market_paths(tmp_path,"NIFTY")["csv"]!=market_paths(tmp_path,"SENSEX")["csv"]
    assert unavailable_snapshot("SENSEX","NO_FILE")["sessions"]==[]
    with pytest.raises(ValueError, match="INVALID_MARKET_SYMBOL"):
        select_symbol("BANKNIFTY")


def test_multi_server_shows_independent_unavailable_market(tmp_path):
    server=ThreadingHTTPServer(
        ("127.0.0.1",0),
        make_handler("not-used","not-used",None,multi_root=tmp_path))
    worker=Thread(target=server.serve_forever,daemon=True)
    worker.start()
    try:
        url=f"http://127.0.0.1:{server.server_port}/api/snapshot?symbol="
        with urlopen(url+"NIFTY") as response:
            nifty=json.load(response)
        with urlopen(url+"SENSEX") as response:
            sensex=json.load(response)
        assert nifty["symbol"]=="NIFTY"
        assert sensex["symbol"]=="SENSEX"
        assert sensex["historical_available"] is False
        assert sensex["sessions"]==[]
        assert nifty["orders_enabled"] is False
        with pytest.raises(HTTPError) as error:
            urlopen(url+"INVALID")
        assert error.value.code==400
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=4)


def test_selector_and_opt_in_alert_controls_exist():
    assert 'id="market"' in HTML
    assert 'value="NIFTY"' in HTML
    assert 'value="SENSEX"' in HTML
    assert 'id="bigAlert"' in HTML
    assert "Notification.requestPermission" in HTML
    assert "SMC RETEST OBSERVED" in HTML
    assert "/api/live?symbol=" in HTML


def test_retest_alert_requires_current_closed_bar_not_historical_stale(tmp_path):
    path=market_paths(tmp_path,"NIFTY")
    write_live_status(str(path["status"]),"SUBSCRIBING","BROKER_SUBSCRIBED")
    now=datetime.now(IST).isoformat()
    setup_id="2026-11-16T10:04:00+05:30:BULLISH"
    event={
        "research_only":True,"orders_enabled":False,"status":"RESEARCH_ONLY",
        "last_candle_close_at":now,"last_candle_close":25200.0,
        "stream_quality":{"quality_blocked":False},
        "symbol":"NIFTY",
        "ict_active_lifecycles":[{
            "state":"RETEST_CONFIRMED_RESEARCH","direction":"BULLISH",
            "retest_at":now,"setup_id":setup_id
        }],
    }
    path["live"].parent.mkdir(parents=True,exist_ok=True)
    path["live"].write_text(json.dumps(event)+"\n")
    result=live_screen_payload(path["live"],path["status"])
    assert result["status"]=="RECENT_BAR"
    assert result["alert"]["type"]=="SMC_RETEST_RESEARCH"
    assert result["alert"]["order_eligible"] is False
    event["ict_active_lifecycles"][0]["retest_at"]=(datetime.now(IST)-timedelta(minutes=1)).isoformat()
    path["live"].write_text(json.dumps(event)+"\n")
    result=live_screen_payload(path["live"],path["status"])
    assert result["alert"] is None


class FakeSocket:
    def __init__(self):
        self.on_open=self.on_data=self.on_error=self.on_close=None
        self.subscribed=None
        self.closed=False

    def subscribe(self,correlation,mode,groups):
        self.subscribed=(correlation,mode,groups)

    def close_connection(self):
        self.closed=True

    def connect(self):
        self.on_open(self)
        # Two genuine exchange-timestamped tick packets for independent markets.
        for exchange,token in ((1,"111"),(3,"222")):
            at=datetime.now(timezone.utc)
            packet={
                "subscription_mode":1,"exchange_type":exchange,
                "token":token,"exchange_timestamp":int(at.timestamp()*1000),
                "sequence_number":1,"last_traded_price":2500000 if exchange==1 else 8000000,
            }
            self.on_data(self,packet)


def test_one_session_subscribes_both_indices_no_orders(tmp_path):
    ws=FakeSocket()
    outputs={"NIFTY":io.StringIO(),"SENSEX":io.StringIO()}
    statuses={s:str(tmp_path/f"{s}.json") for s in outputs}
    totals=run_dual_stream(ws=ws,tokens={"NIFTY":"111","SENSEX":"222"},
                           outputs=outputs,statuses=statuses,max_seconds=5)
    assert ws.subscribed[1]==1
    assert ws.subscribed[2]==[
        {"exchangeType":1,"tokens":["111"]},
        {"exchangeType":3,"tokens":["222"]}]
    assert ws.closed
    assert set(totals)=={"NIFTY","SENSEX"}
    # Each market uses its own closed-candle warmup and no broker orders.
    assert all(v["candles"]==0 for v in totals.values())
    assert all(json.loads(open(path,encoding="utf-8").read())["orders_enabled"] is False
               for path in statuses.values())
