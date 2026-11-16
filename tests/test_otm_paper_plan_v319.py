"""End-to-end research-only OTM choice / paper premium plan guards."""
import json
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo

from smc.angel_option_live_v318 import select_chain_candidates,fetch_option_snapshot
from smc.premium_paper_plan_v319 import create_paper_plan
from smc.self_learning_cli_v319 import read_index_signals,read_observed_quotes,run_learning
from smc.app_terminal_v316 import HTML

IST=ZoneInfo("Asia/Kolk")
T=datetime(2026,11,16,10,5,tzinfo=ZoneInfo("Asia/Kolkata"))


def option_master(symbol="NIFTY",exchange="NFO",spot=25000):
    return [{
        "exch_seg":exchange,"instrumenttype":"OPTIDX",
        "symbol":f"{symbol}17NOV26{price}{side}",
        "token":f"{price}{side}","expiry":"17NOV2026",
        "lotsize":"75","strike":str(price*100)
    } for price in range(spot-500,spot+501,50) for side in ("CE","PE")]


def test_chain_includes_far_otm_but_stops_at_8_steps():
    chain=select_chain_candidates(option_master(),symbol="NIFTY",
                                  spot=25000,as_of=T)
    assert any(c["side"]=="CE" and c["moneyness"]=="OTM" and
               c["strike"]==25400 for c in chain)
    assert any(c["side"]=="PE" and c["moneyness"]=="OTM" and
               c["strike"]==24600 for c in chain)
    assert not any(c["strike"] in (25450,24550) for c in chain)
    assert len(chain)<=20


def test_chain_quotes_request_real_broker_otm_tokens():
    class Client:
        def getMarketData(self,mode,tokens):
            assert mode=="FULL"
            assert "25400CE" in tokens["NFO"]
            assert "24600PE" in tokens["NFO"]
            return {"status":True,"data":{"fetched":[]}}
    result=fetch_option_snapshot(Client(),option_master(),
        symbol="NIFTY",spot=25000,received_at=T)
    assert result["status"]=="UNAVAILABLE"
    assert result["orders_enabled"] is False


def index_setup():
    return {"research_only":True,
            "index_research_bracket_status":"RESEARCH_INDEX_BRACKET_PASSES",
            "setup_state":"RETEST_CONFIRMED_RESEARCH",
            "instrument_side":"CE"}

def momentum():
    return {"research_only":True,"orders_enabled":False,
            "candidates":[{
                "trading_symbol":"NIFTY17NOV2625400CE","side":"CE","moneyness":"OTM",
                "entry_ask_reference":42.0,"last_bid":41.7,
                "score":5.1,"quote_at":T.isoformat(),"bid_change_pct":7.0,
                "volume_growth":140,
            }]}

def learning():
    return {"research_only":True,"orders_enabled":False,
            "promotion_allowed":False,"status":"PAPER_RESEARCH_CANDIDATE",
            "selected":{"target_premium_points":20,"stop_premium_points":8,
                        "cost_per_unit":1}}


def test_far_otm_paper_plan_research_level_only():
    p=create_paper_plan(index_setup(),momentum(),learning())
    assert p["status"]=="READY_FOR_PAPER_OBSERVATION"
    assert p["moneyness"]=="OTM"
    assert p["entry_ask_reference"]==42.0
    assert p["premium_stop_reference"]==34.0
    assert p["premium_target_reference"]==62.0
    assert p["net_rr_reference"]>=2
    assert p["orders_enabled"] is False
    assert p["premium_target_hit_observed"] is False


def test_no_holdout_or_no_momentum_never_generates_entry():
    failed={**learning(),"status":"INSUFFICIENT_EVIDENCE"}
    assert create_paper_plan(index_setup(),momentum(),failed)["status"]=="WAIT"
    assert create_paper_plan(index_setup(),
                             {"orders_enabled":False,"candidates":[]},
                             learning())["entry_ask_reference"] is None
    bad={**index_setup(),"index_research_bracket_status":"NO_VERIFIED_INDEX_BRACKET"}
    assert create_paper_plan(bad,momentum(),learning())["status"]=="WAIT"


def test_source_events_and_quotes_replay_from_disk(tmp_path):
    events=tmp_path/"index.jsonl"
    tape=tmp_path/"options.jsonl"
    stamp=T.isoformat()
    event={
        "symbol":"NIFTY","status":"RESEARCH_ONLY","research_only":True,
        "orders_enabled":False,"last_candle_close_at":stamp,
        "stream_quality":{"quality_blocked":False},
        "index_bracket_research":{"status":"RESEARCH_INDEX_BRACKET_PASSES"},
        "ict_active_lifecycles":[{
            "state":"RETEST_CONFIRMED_RESEARCH",
            "retest_at":stamp,"direction":"BULLISH"
        }]
    }
    row={"market":"NIFTY","research_only":True,"orders_enabled":False,
         "quote_at":(T+timedelta(seconds=25)).isoformat(),
         "expiry":"2026-11-17","side":"CE","strike":25400,"bid":42,"ask":43,
         "lot_size":75,"volume":140}
    events.write_text(json.dumps(event)+"\n")
    tape.write_text(json.dumps(row)+"\n")
    assert len(read_index_signals(events,market="NIFTY"))==1
    assert len(read_observed_quotes(tape,market="NIFTY"))==1
    report=run_learning(market="NIFTY",event_file=events,quote_file=tape)
    assert report["status"]=="INSUFFICIENT_EVIDENCE"
    assert report["recorded_signals"]==1
    assert report["observed_quote_samples"]==1
    assert report["promotion_allowed"] is False


def test_dashboard_has_leaderboard_and_paper_plan():
    assert "OPTION MOMENTUM RANKING" in HTML
    assert 'id="momentumRows"' in HTML
    assert 'id="premiumPlanMetrics"' in HTML
    assert 'id="learningMetrics"' in HTML
    assert "PAPER ONLY" in HTML
