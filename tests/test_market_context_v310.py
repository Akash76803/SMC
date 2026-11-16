"""V3.10 causal intraday structure, previous-day and weekly safety tests."""
from datetime import datetime, timedelta, timezone
import json

import pytest

from smc.context_liquidity_v310 import contextual_liquidity
from smc.market_context_v310 import analyze_mtf, closed_timeframes
from smc.models import Candle
from smc.continuation_validation_cli import build_report

IST = timezone(timedelta(hours=5, minutes=30))


def session(day=2, *, base=100.0):
    first = datetime(2026, 11, day, 9, 16, tzinfo=IST)
    return [
        Candle(first + timedelta(minutes=i), base+i*0.05,
               base+i*0.05+1, base+i*0.05-1, base+i*0.05+0.25)
        for i in range(360)
    ]


def test_closed_timeframe_counts_are_actual_session_buckets():
    c = session()
    x = closed_timeframes(c, as_of=c[-1].timestamp)
    assert [len(x[t]) for t in ("5m", "15m", "1h", "daily")] == [72, 24, 6, 1]
    assert x["5m"][0].timestamp == c[4].timestamp
    assert x["1h"][0].timestamp == c[59].timestamp
    assert x["1h"][-1].timestamp == c[-1].timestamp


def test_no_future_htf_bar_at_intermediate_confirmation():
    c = session()
    x = closed_timeframes(c, as_of=c[72].timestamp)
    assert [len(x[t]) for t in ("5m", "15m", "1h", "daily")] == [14, 4, 1, 0]
    assert all(bar.timestamp <= c[72].timestamp for bars in x.values() for bar in bars)


def test_last_observed_bar_cannot_create_partial_hour():
    c = session()[:119]
    x = closed_timeframes(c, as_of=c[-1].timestamp)
    assert len(x["1h"]) == 1
    assert len(x["daily"]) == 0


def test_mtf_alignment_does_not_claim_monthly_weekly_daily():
    c = session()
    r = analyze_mtf(c, as_of=c[-1].timestamp, direction="BULLISH")
    assert r["independent_monthly_weekly_daily_verified"] is False
    assert r["research_only"] is True
    assert set(r["timeframes"]) == {"1h", "15m", "5m"}
    assert r["alignment"] in (
        "UNVERIFIED", "CONFLICT", "ALIGNED_BULLISH", "ALIGNED_BEARISH")


def test_gap_refused_instead_of_fabricating_bar():
    c = session()
    del c[27]
    with pytest.raises(ValueError, match="INTRADAY_MTF_GAP"):
        closed_timeframes(c, as_of=c[-1].timestamp)


def test_prior_observed_day_not_automatically_verified_calendar_day():
    c = session(2) + session(3, base=120)
    r = contextual_liquidity(c, as_of=c[-1].timestamp)
    assert r["prior_observed_day"]["date"] == "2026-11-02"
    assert r["prior_observed_day"]["is_verified_immediate_predecessor"] is False
    assert not any(x["kind"] in ("PDH", "PDL") for x in r["levels"])


def test_explicit_verified_predecessor_can_supply_pdh_pdl():
    c = session(2) + session(3, base=120)
    r = contextual_liquidity(
        candles=c, as_of=c[-1].timestamp,
        verified_predecessors=frozenset({"2026-11-03"}))
    level = {x["kind"]: x for x in r["levels"] if x["kind"] in ("PDH", "PDL")}
    assert set(level) == {"PDH", "PDL"}
    assert level["PDH"]["price"] == max(x.high for x in c[:360])
    assert level["PDL"]["price"] == min(x.low for x in c[:360])


def test_no_automatic_weekly_from_last_supplied_date():
    c = session(2) + session(3, base=120)
    r = contextual_liquidity(candles=c, as_of=c[-1].timestamp)
    assert r["completed_week"] is None


def test_marked_week_is_informational_not_trade_authorization():
    c = session(2) + session(3, base=120)
    r = contextual_liquidity(candles=c, as_of=c[-1].timestamp,
                             verified_week_ends=frozenset({"2026-11-02"}))
    assert r["completed_week"]["calendar_marker_verified"] is True
    assert r["completed_week"]["history_completeness_independently_verified"] is False
    assert "PWH" not in {x["kind"] for x in r["levels"]}


def test_report_with_full_context_keeps_nonexecutable_invariant():
    c = session(2)
    report = build_report(symbol="NIFTY", candles=c, context_candles=c)
    assert report["schema_version"] == "3.10"
    assert report["qualified_trades"] == 0
    assert report["live_orders_enabled"] is False
    assert report["research_only"] is True
    assert json.loads(json.dumps(report)) == report


def test_context_current_session_must_equal_requested_session():
    c = session(2)
    changed = session(2, base=200)
    with pytest.raises(ValueError, match="CONTEXT_CURRENT_SESSION_MISMATCH"):
        build_report(symbol="NIFTY", candles=c, context_candles=changed)


def test_multiday_context_cannot_feed_future_to_past():
    first = session(2)
    nextday = session(3, base=120)
    report = build_report(symbol="NIFTY", candles=first,
                          context_candles=first+nextday)
    assert report["qualified_trades"] == 0
    assert report["live_orders_enabled"] is False

def test_unknown_verified_calendar_marker_is_rejected():
    c = session(2) + session(3, base=120)
    with pytest.raises(ValueError, match="UNOBSERVED_WEEK_END_MARKER"):
        contextual_liquidity(candles=c, as_of=c[-1].timestamp,
                             verified_week_ends=frozenset({"2026-11-06"}))
    with pytest.raises(ValueError, match="UNOBSERVED_PREDECESSOR_MARKER"):
        contextual_liquidity(candles=c, as_of=c[-1].timestamp,
                             verified_predecessors=frozenset({"2026-11-06"}))
