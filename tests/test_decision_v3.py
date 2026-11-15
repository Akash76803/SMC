import pytest
from smc.decision_v3 import (CheckState, DecisionStatus, EvidenceCheck,
                             ResearchBracket, decide_setup)

def checks(state=CheckState.PASS):
    return [EvidenceCheck("HTF_BIAS", state, "Closed HTF candles aligned", "h1:42")]

def call(symbol="NIFTY", **kwargs):
    opts = dict(symbol=symbol, strategy="SWEEP_MSS_RETEST", checks=checks(),
                bracket=ResearchBracket(25000, 24970, 25065, "BULLISH"),
                data_healthy=True, option_data_verified=True)
    opts.update(kwargs)
    return decide_setup(**opts)

def test_data_failure_overrides_other_conditions():
    d = call(data_healthy=False)
    assert d.status is DecisionStatus.DATA_BLOCKED
    assert d.primary_reason == "DATA_UNVERIFIED_OR_STALE"

def test_wait_when_confirmation_pending():
    d = call(checks=checks(CheckState.PENDING))
    assert d.status is DecisionStatus.WAIT and d.primary_reason == "HTF_BIAS"

def test_no_trade_when_failed():
    assert call(checks=checks(CheckState.FAIL)).status is DecisionStatus.NO_TRADE

def test_no_signal_without_evidence_or_bracket():
    assert call(checks=[]).status is DecisionStatus.WAIT
    assert call(bracket=None).primary_reason == "ENTRY_SL_TARGET_NOT_VERIFIED"

def test_index_rr_and_target_constraints():
    assert call(bracket=ResearchBracket(25000,24980,25040,"BULLISH")).primary_reason == "INDEX_TARGET_TOO_SMALL"
    assert call(bracket=ResearchBracket(25000,24950,25065,"BULLISH")).primary_reason == "INDEX_RR_BELOW_MINIMUM"
    assert call("SENSEX", bracket=ResearchBracket(73000,72950,73090,"BULLISH")).primary_reason == "INDEX_TARGET_TOO_SMALL"

def test_option_data_missing_does_not_mark_ready():
    d = call(option_data_verified=False)
    assert d.status is DecisionStatus.WAIT
    assert d.primary_reason == "OPTION_QUOTES_GREEKS_NOT_VERIFIED"

def test_research_ready_is_not_live_trade_authorization():
    d = call()
    assert d.status is DecisionStatus.RESEARCH_READY
    assert d.research_only and d.as_dict()["research_only"] is True
    assert d.as_dict()["checks"][0]["source_id"] == "h1:42"

def test_invalid_brackets_rejected():
    with pytest.raises(ValueError):
        ResearchBracket(25000,25010,25100,"BULLISH")
    with pytest.raises(ValueError):
        ResearchBracket(25000,24900,25100,"BEARISH")

def test_no_duplicate_evidence():
    with pytest.raises(ValueError):
        call(checks=checks()+checks())
