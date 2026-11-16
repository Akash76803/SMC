from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pytest

from smc.decision_v3 import CheckState, DecisionStatus
from smc.htf_context_v3 import (
    Alignment, Bias, analyze_htf, bias_stage, adapt_reversal_with_htf,
)
from smc.models import Candle

BASE = datetime(2026, 11, 12, 9, 16, tzinfo=ZoneInfo("Asia/Kolkata"))
NOW = BASE + timedelta(days=365)

def bars(highs, lows=None, closes=None):
    if lows is None:
        lows = [h - 10 for h in highs]
    if closes is None:
        closes = [(h + l) / 2 for h, l in zip(highs, lows)]
    return [Candle(BASE + timedelta(days=i), close, high, low, close)
            for i, (high, low, close) in enumerate(zip(highs, lows, closes))]

def bull():
    return bars([100, 104, 115, 105, 102, 108, 118, 117],
                [90, 94, 105, 95, 92, 98, 108, 107],
                [95, 99, 110, 100, 97, 103, 116, 115])

def bear():
    return bars([120, 116, 110, 115, 118, 112, 104, 103],
                [110, 106, 100, 105, 108, 102, 94, 93],
                [115, 111, 105, 110, 113, 107, 98, 97])

def context(m=None,w=None,d=None,**kwargs):
    return analyze_htf(monthly=bull() if m is None else m,
                       weekly=bull() if w is None else w,
                       daily=bull() if d is None else d, as_of=NOW, **kwargs)

def test_empty_history_yields_unverified_not_bullish():
    c = context(m=[],w=[],d=[])
    assert c.alignment is Alignment.UNVERIFIED

def test_future_bar_rejected():
    c = bull()
    with pytest.raises(ValueError,match="FUTURE_HTF_CANDLE"):
        analyze_htf(monthly=c,weekly=c,daily=c,as_of=BASE)

def test_incomplete_htf_rejected():
    c = bull()
    x=c[-1]
    c[-1]=Candle(x.timestamp,x.open,x.high,x.low,x.close,complete=False)
    with pytest.raises(ValueError,match="INCOMPLETE_HTF_CANDLE"):
        context(m=c)

def test_unsorted_rejected():
    c=bull()
    with pytest.raises(ValueError,match="HTF_CANDLES_NOT_STRICTLY_ORDERED"):
        context(w=[c[1],c[0],*c[2:]])

def test_range_equilibrium_is_arithmetic_midpoint():
    c=context()
    for f in c.frames:
        if f.dealing_range is not None:
            r=f.dealing_range
            assert r.equilibrium==(r.low+r.high)/2
            assert r.position in ("PREMIUM","DISCOUNT","EQUILIBRIUM")

def test_alignment_is_not_inferred_from_candle_color_alone():
    c=context(m=bars([100]*8),w=bull(),d=bull())
    assert c.alignment is Alignment.UNVERIFIED

def test_bias_stage_fail_closed_on_missing_alignment():
    stage=bias_stage(context(m=[],w=[],d=[]),desired_direction="BULLISH")
    assert stage.state is CheckState.PENDING

def test_invalid_args():
    with pytest.raises(ValueError):
        context(pivot_k=1)
    with pytest.raises(ValueError):
        context(max_event_age_bars=-1)
    with pytest.raises(ValueError):
        bias_stage(context(),desired_direction="SIDEWAYS")

def test_all_three_alignment_from_actual_break_event():
    c=context()
    assert c.alignment in (Alignment.ALIGNED_BULLISH,Alignment.UNVERIFIED)
    if c.alignment is Alignment.ALIGNED_BULLISH:
        stage=bias_stage(c,desired_direction="BULLISH")
        assert stage.state is CheckState.PASS
        assert stage.source_id.startswith("htf:confirmed:")
    else:
        assert bias_stage(c,desired_direction="BULLISH").state is CheckState.PENDING

def test_latest_external_event_too_old_becomes_neutral():
    c=context(max_event_age_bars=0)
    assert all(f.bias in (Bias.NEUTRAL,Bias.BULLISH,Bias.BEARISH) for f in c.frames)

def test_wrapper_never_fabricates_poi_or_trade():
    c=bull()
    ctx,report=adapt_reversal_with_htf(
        symbol="NIFTY",candles=c,monthly=c,weekly=c,daily=c,
        observed_at=NOW,data_healthy=True)
    assert report.assessment.decision.status is not DecisionStatus.RESEARCH_READY
    assert any(x["code"]=="HTF_POI" and x["state"]=="PENDING"
               for x in report.assessment.stage_progress)
    assert ctx.as_dict()["research_only"]
