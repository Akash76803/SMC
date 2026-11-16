"""Continuation V3.9B strict HTF/risk/target gate tests."""
from datetime import datetime, timedelta, timezone

import pytest

from smc.continuation_v3 import ContinuationObservation
from smc.continuation_validation_v3 import validate_continuation
from smc.htf_context_v3 import Alignment, HTFContext
from smc.liquidity import LiquidityLevel
from smc.models import Candle


T = datetime(2026, 11, 2, 9, 16, tzinfo=timezone(timedelta(hours=5, minutes=30)))


def data():
    rows = [(100, 101, 99, 100), (100, 102, 99, 101),
            (101, 104, 100, 103), (103, 106, 102, 105),
            (105, 106, 101, 102), (102, 107, 101, 106.5)]
    return [Candle(T + timedelta(minutes=i), *row) for i, row in enumerate(rows)]


def observation():
    return ContinuationObservation("BULLISH", 3, 4, 5, 102, 106, 106.5)


def context(as_of=None, alignment=Alignment.UNVERIFIED):
    return HTFContext((), alignment, "NO_VERIFIED_MONTHLY_WEEKLY_DAILY",
                      as_of or T)


def verify(candles=None, levels=None, ctx=None):
    return validate_continuation(
        symbol="NIFTY", candles=data() if candles is None else candles,
        observation=observation(), context=ctx or context(),
        levels=[] if levels is None else levels, events=[])


def test_no_liquidity_evidence_stays_wait():
    x = verify().as_dict()
    assert x["status"] == "WAIT"
    assert x["reason"] == "LIQUIDITY_TARGET_UNVERIFIED"
    assert x["entry_reference"] == 106.5
    assert x["stop_reference"] == 101
    assert x["risk_points"] == 5.5
    assert x["index_bracket"] is None
    assert x["live_orders_enabled"] is False
    assert "VERIFIED_HTF_BIAS" in x["pending_stages"]


def test_distant_visible_target_is_still_not_trade_permission():
    lev = LiquidityLevel("BSL", 180, 2, (1,), 3)
    x = verify(levels=[lev]).as_dict()
    assert x["status"] == "WAIT"
    assert x["target_level"] == 180
    assert x["target_points"] == 73.5
    assert x["index_rr"] > 2
    assert "HTF_BIAS" in x["reason"]
    assert x["index_bracket"] is None


def test_close_target_rejected_even_if_other_evidence_missing():
    lev = LiquidityLevel("BSL", 110, 2, (1,), 3)
    x = verify(levels=[lev]).as_dict()
    assert x["status"] == "NO_TRADE"
    assert x["reason"] == "INDEX_TARGET_TOO_SMALL"
    assert x["target_points"] == 3.5


def test_future_confirmed_liquidity_level_cannot_backfill():
    lev = LiquidityLevel("BSL", 180, 6, (1,), 7)
    x = verify(levels=[lev]).as_dict()
    assert x["target_level"] is None
    assert x["reason"] == "LIQUIDITY_TARGET_UNVERIFIED"


def test_spot_at_target_is_not_unconsumed_liquidity():
    lev = LiquidityLevel("BSL", 107, 2, (1,), 3)
    x = verify(levels=[lev]).as_dict()
    assert x["target_level"] == 107
    assert x["status"] == "NO_TRADE"


def test_future_htf_context_rejected():
    with pytest.raises(ValueError, match="FUTURE_HTF_CONTEXT"):
        verify(ctx=context(T + timedelta(days=1)))


def test_invalid_observation_indices_fail_closed():
    bad = ContinuationObservation("BULLISH", 5, 4, 3, 102, 106, 106.5)
    with pytest.raises(ValueError, match="INVALID_CONTINUATION_EVENT_INDICES"):
        validate_continuation(
            symbol="NIFTY", candles=data(), observation=bad, context=context(),
            levels=[], events=[])


def test_no_cross_session_carry():
    c = data()
    c[-1] = Candle(T + timedelta(days=1), 102, 107, 101, 106.5)
    with pytest.raises(ValueError, match="CROSS_SESSION"):
        verify(candles=c)


def test_aligned_context_does_not_override_missing_protected_poi():
    lev = LiquidityLevel("BSL", 180, 2, (1,), 3)
    x = verify(levels=[lev], ctx=context(alignment=Alignment.ALIGNED_BULLISH)).as_dict()
    assert x["status"] == "WAIT"
    assert x["reason"] == "PROTECTED_POI_OPTION_EVIDENCE_PENDING"
    assert "PROTECTED_STRUCTURE" in x["pending_stages"]

def test_cli_report_empty_session_stays_research_only():
    from smc.continuation_validation_cli import build_report
    session = [
        Candle(T + timedelta(minutes=i), 100, 101, 99, 100)
        for i in range(360)
    ]
    report = build_report(symbol="NIFTY", candles=session)
    assert report["observed_bars"] == 360
    assert report["continuation_observations"] == 0
    assert report["qualified_trades"] == 0
    assert report["option_pnl"] is None
    assert report["live_orders_enabled"] is False


def test_cli_report_rejects_partial_session():
    from smc.continuation_validation_cli import build_report
    with pytest.raises(ValueError, match="AUDITED_COMPLETE_REGULAR_SESSION"):
        build_report(symbol="NIFTY", candles=data())
