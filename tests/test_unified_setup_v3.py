"""V3.5 integration checks: no false READY, no future-target leakage."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from smc.decision_v3 import DecisionStatus
from smc.models import Candle
from smc.setup_confirmation_v3 import PremiumPlan
from smc.unified_setup_v3 import evaluate_unified_reversal

BASE = datetime(2026, 11, 16, 9, 16, tzinfo=ZoneInfo("Asia/Kolkata"))

def bars(highs):
    return [Candle(BASE+timedelta(minutes=i),h-5,h,h-10,h-5)
            for i,h in enumerate(highs)]

def run(ltf=None, **kwargs):
    candles = bars([100,102,110,103,102,111,101,100,104,108,112,104]) if ltf is None else ltf
    args = dict(symbol="NIFTY",ltf=candles,monthly=[],weekly=[],daily=[],
                observed_at=candles[-1].timestamp if candles else BASE,
                data_healthy=True)
    args.update(kwargs)
    return evaluate_unified_reversal(**args)

def test_no_fake_ready_with_hypothetical_premium_and_quote_flag():
    a=run(premium_plan=PremiumPlan(15,3,1),option_data_verified=True)
    assert a.status is not DecisionStatus.RESEARCH_READY
    assert a.as_dict()["research_only"] is True
    assert a.as_dict()["live_orders_enabled"] is False

def test_no_data_yields_blocked():
    assert run(ltf=[],observed_at=BASE).status is DecisionStatus.DATA_BLOCKED

def test_feed_health_not_assumed():
    assert run(data_healthy=False).status is DecisionStatus.DATA_BLOCKED

def test_nonfinal_candle_blocks():
    c=bars([100,110,105])
    last=c[-1]
    c[-1]=Candle(last.timestamp,last.open,last.high,last.low,last.close,complete=False)
    assert run(ltf=c).status is DecisionStatus.DATA_BLOCKED

def test_future_ltf_candle_rejected():
    c=bars([100,110,105])
    with pytest.raises(ValueError,match="FUTURE_CANDLE_INPUT"):
        run(ltf=c,observed_at=c[1].timestamp)

def test_no_historical_htf_can_be_manufactured():
    a=run()
    stages=a.evidence.assessment.stage_progress
    assert any(s["code"]=="HTF_BIAS" and s["state"]=="PENDING" for s in stages)

def test_no_candidate_has_no_index_bracket():
    c=bars([100]*12)
    a=run(ltf=c)
    assert a.index_bracket is None
    assert a.target_review is None
    assert a.as_dict()["index_bracket"] is None

def test_no_ob_fvg_candidate_is_not_passed_as_htf_poi():
    a=run()
    assert any(s["code"]=="HTF_POI" and s["state"]=="PENDING"
               for s in a.evidence.assessment.stage_progress)

def test_unverified_quote_has_no_live_authority():
    a=run(option_data_verified=False)
    assert a.as_dict()["setup"]["research_only"]
    assert a.status is not DecisionStatus.RESEARCH_READY

def test_invalid_symbol_rejected():
    with pytest.raises(ValueError,match="UNSUPPORTED_SYMBOL"):
        run(symbol="BANKNIFTY")

def test_missing_timezone_rejected():
    with pytest.raises(ValueError,match="OBSERVED_AT_REQUIRES_OFFSET"):
        run(observed_at=datetime(2026,11,16,9,16))

def test_htf_future_bars_do_not_enter_historical_context():
    a=run(monthly=bars([100]*12),weekly=bars([100]*12),daily=bars([100]*12))
    assert all(f.available_at is None or f.available_at<=a.context.as_of
               for f in a.context.frames)

def test_report_serialization_contains_index_and_premium_separately():
    a=run(premium_plan=PremiumPlan(15,3,1))
    out=a.as_dict()
    assert out["schema_version"]=="3.5"
    assert "target_review" in out and "poi_review" in out
    assert "premium_feasibility" in out["setup"]
