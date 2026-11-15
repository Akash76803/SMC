from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pytest
from smc.models import Candle
from smc.decision_v3 import CheckState, DecisionStatus, ResearchBracket
from smc.setup_confirmation_v3 import ObservedStage, PremiumPlan
from smc.evidence_adapter_v3 import adapt_reversal_candles

BASE=datetime(2026,11,12,9,16,tzinfo=ZoneInfo("Asia/Kolkata"))
def bars(highs):
    return [Candle(BASE+timedelta(minutes=i), h-5,h,h-10,h-5)
            for i,h in enumerate(highs)]

def run(candles=None,**kwargs):
    c=bars([100,102,110,103,102,111,101,100,104,108,112,104]) if candles is None else candles
    args=dict(symbol="NIFTY",candles=c,observed_at=c[-1].timestamp,
              data_healthy=True)
    args.update(kwargs)
    return adapt_reversal_candles(**args)

def test_no_fabricated_ready_without_htf_and_option_data():
    a=run()
    assert a.assessment.decision.status is DecisionStatus.WAIT
    assert a.assessment.next_confirmation in ("HTF_BIAS","HTF_POI")
    assert a.as_dict()["research_only"] is True

def test_default_unverified_feed_blocks():
    a=run(data_healthy=False)
    assert a.assessment.decision.status is DecisionStatus.DATA_BLOCKED
    assert a.selected_sweep_index is None

def test_empty_data_fails_closed():
    a=adapt_reversal_candles(symbol="NIFTY",candles=[],
             observed_at=BASE,data_healthy=True)
    assert a.assessment.decision.status is DecisionStatus.DATA_BLOCKED

def test_incomplete_bar_fails_closed():
    c=bars([100,110,105])
    x=c[-1]
    c[-1]=Candle(x.timestamp,x.open,x.high,x.low,x.close,complete=False)
    assert run(c).assessment.decision.status is DecisionStatus.DATA_BLOCKED

def test_future_candle_rejected():
    c=bars([100,110,105])
    with pytest.raises(ValueError,match="FUTURE_CANDLE_INPUT"):
        run(c,observed_at=c[1].timestamp)

def test_htf_evidence_must_be_explicit():
    stage=ObservedStage("HTF_BIAS",CheckState.PASS,"Verified external HTF bias",BASE,"htf:close:0")
    a=run(verified_htf=(stage,))
    assert any(s["code"]=="HTF_BIAS" and s["state"]=="PASS"
               for s in a.assessment.stage_progress)
    assert a.assessment.decision.status is DecisionStatus.WAIT

def test_prohibits_injected_ltf_stages():
    with pytest.raises(ValueError,match="ONLY_HTF_STAGES_ACCEPTED"):
        run(verified_htf=(ObservedStage("RETEST_CONFIRMED",CheckState.PENDING,"No"),))

def test_duplicate_htf_rejected():
    stage=ObservedStage("HTF_POI",CheckState.PENDING,"No zone")
    with pytest.raises(ValueError,match="DUPLICATE_HTF_STAGE"):
        run(verified_htf=(stage,stage))

def test_candidate_premium_and_bracket_cannot_bypass_missing_confirmations():
    a=run(index_bracket=ResearchBracket(25000,24970,25080,"BULLISH"),
          premium_plan=PremiumPlan(15,3,1),option_data_verified=True)
    assert a.assessment.decision.status is DecisionStatus.WAIT

def test_unordered_bars_fail():
    c=bars([100,110,105])
    with pytest.raises(ValueError,match="UNORDERED_CANDLES"):
        run([c[1],c[0],c[2]])

def test_debug_payload_contains_counts_without_implied_fills():
    report=run()
    data=report.as_dict()
    assert data["candle_evidence"]["liquidity_events_count"]>=0
    assert "entry_state" in data["candle_evidence"]
    assert data["research_only"]
