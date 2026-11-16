"""Independent broker-quote normalization: no synthetic prices or Greeks."""
from datetime import datetime, timezone, timedelta

from smc.angel_option_live_v318 import (
    select_atm_itm,fetch_option_snapshot,write_option_snapshot,read_option_snapshot,
)
IST=timezone(timedelta(hours=5,minutes=30))


def master(symbol="NIFTY",exchange="NFO",spot=25000):
    return [{
        "exch_seg":exchange,"instrumenttype":"OPTIDX",
        "symbol":f"{symbol}17NOV26{price}{side}",
        "token":f"{price}{side}",
        "expiry":"17NOV2026","lotsize":"75",
        "strike":str(price*100),
    } for price in (spot-50,spot,spot+50) for side in ("CE","PE")]


def test_current_atm_itm_exact_contracts():
    at=datetime(2026,11,16,10,0,tzinfo=IST)
    rows=select_atm_itm(master(),symbol="NIFTY",spot=25000,as_of=at)
    assert len(rows)==4
    assert {(r["side"],r["moneyness"],r["strike"]) for r in rows}=={
        ("CE","ATM",25000),("CE","ITM",24950),
        ("PE","ATM",25000),("PE","ITM",25050)}


def test_sensex_bfo_routed_without_synthetic_greeks():
    at=datetime(2026,11,16,10,0,tzinfo=IST)
    rows=select_atm_itm(master("SENSEX","BFO",80000),
                        symbol="SENSEX",spot=80000,as_of=at)
    assert len(rows)==4
    assert all(r["exchange"]=="BFO" for r in rows)


def test_no_bid_ask_fails_closed():
    class Client:
        def getMarketData(self,mode,tokens):
            assert mode=="FULL"
            return {"status":True,"data":{"fetched":[]}}
    result=fetch_option_snapshot(Client(),master(),symbol="NIFTY",
                    spot=25000,received_at=datetime(2026,11,16,10,tzinfo=IST))
    assert result["status"]=="UNAVAILABLE"
    assert result["contracts"]==[]
    assert result["premium_exit_prices_verified"] is False
    assert result["orders_enabled"] is False


def test_incomplete_option_depth_does_not_impute_quotes():
    class Client:
        def getMarketData(self,mode,tokens):
            return {"status":True,"data":{"fetched":[{
                "exchange":"NFO","symbolToken":"25000CE",
                "exchFeedTime":"16-Nov-2026 10:00:00",
                "depth":{"buy":[{"price":201,"quantity":100}],"sell":[]},
                "tradeVolume":100,
            }]}}
    result=fetch_option_snapshot(Client(),master(),symbol="NIFTY",
                  spot=25000,received_at=datetime(2026,11,16,10,tzinfo=IST))
    assert result["contracts"]==[]
    assert result["orders_enabled"] is False


def test_authenticated_observed_depth_does_not_infer_option_exits():
    class Client:
        def getMarketData(self,mode,tokens):
            return {"status":True,"data":{"fetched":[{
                "exchange":"NFO","symbolToken":"25000CE",
                "exchFeedTime":"16-Nov-2026 10:00:00",
                "depth":{"buy":[{"price":200,"quantity":50}],
                         "sell":[{"price":202,"quantity":50}]},
                "tradeVolume":200,
            }]}}
    r=fetch_option_snapshot(Client(),master(),symbol="NIFTY",
                  spot=25000,received_at=datetime(2026,11,16,10,tzinfo=IST))
    assert r["status"]=="OBSERVED_OPTION_QUOTES"
    assert len(r["contracts"])==1
    assert r["contracts"][0]["bid"]==200
    assert r["contracts"][0]["ask"]==202
    assert r["contracts"][0]["delta"] is None
    assert r["premium_exit_prices_verified"] is False
    assert r["orders_enabled"] is False


def test_option_snapshot_expires_and_filters_cross_symbol(tmp_path):
    path=tmp_path/"quoted.json"
    now=datetime.now(timezone.utc)
    value={"symbol":"NIFTY","at":now.isoformat(),"research_only":True,
           "orders_enabled":False,"contracts":[]}
    write_option_snapshot(path,value)
    assert read_option_snapshot(path,symbol="NIFTY")["symbol"]=="NIFTY"
    assert read_option_snapshot(path,symbol="SENSEX")["status"]=="UNAVAILABLE"
    value["at"]=(now-timedelta(minutes=5)).isoformat()
    write_option_snapshot(path,value)
    assert read_option_snapshot(path,symbol="NIFTY")["status"]=="UNAVAILABLE"
