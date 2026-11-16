"""Live SMC setup screen acceptance: no unsupported market trade advice."""
from datetime import datetime, timedelta, timezone
import json

from smc.live_setup_screen_v317 import build_setup_screen
from smc.app_terminal_v316 import live_screen_payload, HTML

IST=timezone(timedelta(hours=5,minutes=30))


def event():
    return {
        "research_only":True,"orders_enabled":False,
        "status":"RESEARCH_ONLY","reason":"CLOSED_CANDLE_ANALYSIS",
        "symbol":"NIFTY",
        "last_candle_close_at":datetime.now(IST).isoformat(),
        "last_candle_close":25500.0,
        "sampled_live_candles":[{"timestamp":datetime.now(IST).isoformat(),
                                  "open":25495,"high":25506,"low":25490,"close":25500}],
        "stream_quality":{"quality_blocked":False},
        "ict_last_lifecycle":{
            "direction":"BULLISH","state":"RETEST_CONFIRMED_RESEARCH",
            "structure_kind":"CHoCH","sweep_level":25470,
            "sweep_at":datetime.now(IST).isoformat(),
            "idm_at":datetime.now(IST).isoformat(),
            "idm_level":25475,
            "displacement_confirmed":True,
            "ob_zone":[25480,25490],
            "fvg_zone":[25485,25491],
            "retest_at":datetime.now(IST).isoformat(),
        },
        "ict_active_lifecycles":[],
    }


def test_complete_structure_without_option_quote_not_a_trade():
    setup=build_setup_screen(event(),live_status="RECENT_BAR")
    assert setup["bias"]=="BULLISH"
    assert setup["instrument_side"]=="CE"
    assert setup["setup_state"]=="RETEST_CONFIRMED_RESEARCH"
    assert setup["provisional_stop_reference"]==25470
    assert setup["status"]=="WAIT"
    assert setup["entry"] is None
    assert setup["structural_stop"] is None
    assert setup["t1"] is None
    assert setup["option_strike"] is None
    assert setup["option_premium_target"] is None
    assert "LIVE_OPTION_BID_ASK_GREEKS" in setup["missing_evidence"]
    assert setup["order_eligible"] is False


def test_bearish_pivot_screen_not_fake_pe_strike():
    x=event()
    x["ict_last_lifecycle"].update(direction="BEARISH",ob_zone=[25525,25535],
                                    sweep_level=25550)
    result=build_setup_screen(x,live_status="RECENT_BAR")
    assert result["instrument_side"]=="PE"
    assert result["provisional_stop_reference"]==25550
    assert result["option_strike"] is None


def test_stale_and_disconnected_cannot_promote_setup():
    for state in ("STALE","DISCONNECTED","AUTHENTICATION_REQUIRED","WAIT","CANCELLED"):
        result=build_setup_screen(event(),live_status=state)
        assert result["status"]=="WAIT"
        assert result["entry"] is None
        assert result["bias"] is None
        assert result["order_eligible"] is False


def test_unknown_or_untrusted_event_is_rejected():
    untrusted=event()
    untrusted["orders_enabled"]=True
    assert build_setup_screen(untrusted,live_status="RECENT_BAR")["bias"] is None
    assert build_setup_screen(None,live_status="RECENT_BAR")["status"]=="WAIT"


def test_screen_html_contains_real_render_targets():
    assert 'id="setupmetrics"' in HTML
    assert 'id="setupstate"' in HTML
    assert 'id="liveChart"' in HTML
    assert "MITIGATION_RETEST" not in HTML or "setupmetrics" in HTML
    assert "OPTION PREMIUM" in HTML
    assert "/api/live" in HTML


def test_no_live_data_returns_unavailable_with_no_candles(tmp_path):
    status=live_screen_payload(None,None)
    assert status["status"]=="NOT_CONNECTED"
    assert status["setup"]["entry"] is None
    assert status["sampled_live_candles"]==[]


def test_recent_valid_event_can_populate_chart_but_never_buy(tmp_path):
    from smc.angel_stream_cli_v312 import write_live_status
    status=tmp_path/"status.json"
    events=tmp_path/"live.jsonl"
    write_live_status(str(status),"SUBSCRIBING","WAITING_FOR_VERIFIED_MARKET_TICKS")
    payload=event()
    events.write_text(json.dumps(payload)+"\n")
    result=live_screen_payload(events,status)
    assert result["status"]=="RECENT_BAR"
    assert result["sampled_live_candles"]
    assert result["setup"]["order_eligible"] is False
    assert result["setup"]["option_strike"] is None
