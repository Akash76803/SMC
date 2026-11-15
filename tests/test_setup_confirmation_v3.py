from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pytest
from smc.decision_v3 import CheckState, DecisionStatus, ResearchBracket
from smc.setup_confirmation_v3 import ObservedStage, PremiumPlan, SetupKind, STAGES, assess_setup

NOW = datetime(2026,11,15,13,30,tzinfo=ZoneInfo("Asia/Kolkata"))

def stages(kind=SetupKind.REVERSAL):
    return tuple(ObservedStage(code, CheckState.PASS, "Confirmed",
                 NOW-timedelta(minutes=len(STAGES[kind])-i), f"1m:{i}")
                 for i,code in enumerate(STAGES[kind]))

def assess(**kw):
    args=dict(symbol="NIFTY",kind=SetupKind.REVERSAL,direction="BULLISH",
              observed_at=NOW,stages=stages(),data_healthy=True,
              option_data_verified=True,
              index_bracket=ResearchBracket(25000,24970,25070,"BULLISH"),
              premium_plan=PremiumPlan(15,3,1))
    args.update(kw)
    return assess_setup(**args)

def test_full_confirmed_and_premium_pass_is_research_ready_only():
    a=assess()
    assert a.decision.status is DecisionStatus.RESEARCH_READY
    assert a.decision.research_only and a.premium.net_rr == 3.5
    assert a.as_dict()["stages"][0]["source_id"] == "1m:0"

def test_missing_stage_waits_and_explains_next_confirmation():
    filtered=tuple(s for s in stages() if s.code != "MSS_CONFIRMED")
    a=assess(stages=filtered)
    assert a.decision.status is DecisionStatus.WAIT
    assert a.next_confirmation == "MSS_CONFIRMED"
    assert a.decision.primary_reason == "MSS_CONFIRMED"

def test_expiry_blocks_even_if_all_stages_pass():
    a=assess(setup_created_at=NOW-timedelta(minutes=90))
    assert a.decision.status is DecisionStatus.NO_TRADE
    assert a.decision.primary_reason == "SETUP_EXPIRED"

def test_failed_confirmation_blocks():
    bad=list(stages())
    bad[2]=ObservedStage("HTF_POI",CheckState.FAIL,"Zone invalidated")
    a=assess(stages=tuple(bad))
    assert a.decision.status is DecisionStatus.NO_TRADE
    assert a.decision.primary_reason == "HTF_POI"

def test_premium_15_points_but_cost_adjusted_under_3r_rejected():
    a=assess(premium_plan=PremiumPlan(15,5,1))
    assert a.decision.status is DecisionStatus.NO_TRADE
    assert a.decision.primary_reason == "PREMIUM_FEASIBILITY"
    assert a.premium.reason == "NET_PREMIUM_RR_BELOW_3"

def test_missing_premium_is_wait_not_ready():
    a=assess(premium_plan=None)
    assert a.decision.status is DecisionStatus.WAIT
    assert a.next_confirmation == "PREMIUM_PLAN"

def test_quotes_unverified_never_ready():
    a=assess(option_data_verified=False)
    assert a.decision.status is DecisionStatus.WAIT
    assert a.next_confirmation == "OPTION_QUOTES_GREEKS"

def test_bad_feed_fails_closed():
    assert assess(data_healthy=False).decision.status is DecisionStatus.DATA_BLOCKED

def test_continuation_uses_different_stage_set():
    a=assess(kind=SetupKind.CONTINUATION,stages=stages(SetupKind.CONTINUATION))
    assert a.decision.status is DecisionStatus.RESEARCH_READY
    assert [s["code"] for s in a.stage_progress] == list(STAGES[SetupKind.CONTINUATION])

def test_incorrect_direction_rejected():
    with pytest.raises(ValueError,match="BRACKET_DIRECTION_MISMATCH"):
        assess(direction="BEARISH")

def test_future_evidence_rejected():
    newer=ObservedStage("HTF_BIAS",CheckState.PASS,"Unverified future",NOW+timedelta(minutes=1),"h1:99")
    with pytest.raises(ValueError,match="FUTURE_STAGE_EVIDENCE"):
        assess(stages=(newer,))

def test_pass_requires_timestamp_and_source():
    with pytest.raises(ValueError,match="PASS_REQUIRES"):
        ObservedStage("HTF_BIAS",CheckState.PASS,"No proof")

def test_duplicate_and_unknown_stages_rejected():
    with pytest.raises(ValueError,match="DUPLICATE_OR_UNKNOWN"):
        assess(stages=stages() + (stages()[0],))
    with pytest.raises(ValueError,match="DUPLICATE_OR_UNKNOWN"):
        assess(stages=(ObservedStage("OTHER",CheckState.PENDING,"unknown"),))

def test_both_index_and_premium_gates_required():
    a=assess(index_bracket=ResearchBracket(25000,24960,25070,"BULLISH"))
    assert a.decision.status is DecisionStatus.NO_TRADE
    assert a.decision.primary_reason == "INDEX_RR_BELOW_MINIMUM"

def test_no_future_setup_creation():
    with pytest.raises(ValueError,match="SETUP_CREATED_IN_FUTURE"):
        assess(setup_created_at=NOW+timedelta(minutes=1))
