"""ICT lifecycle state acceptance tests (research only)."""
from datetime import datetime, timedelta, timezone

import pytest

from smc.models import Candle
from smc.ict_lifecycle_v316 import scan_ict_lifecycles
from smc.angel_historical_research_cli_v313 import analyze_downloaded

IST=timezone(timedelta(hours=5,minutes=30))
START=datetime(2026,11,2,9,16,tzinfo=IST)


def candles(n=80):
    return [Candle(START+timedelta(minutes=i),
                   100+(i*7%23)*.7, 103+(i*7%23)*.7,
                   98+(i*7%23)*.7, 101+(i*7%23)*.7)
            for i in range(n)]


def test_lifecycle_is_research_only_for_all_states():
    entries=scan_ict_lifecycles(candles())
    assert isinstance(entries,list)
    assert all(not row["order_allowed"] and row["research_only"] for row in entries)
    assert all(not row["stop_protected_verified"] for row in entries)


def test_lifecycle_prefix_equivalence_no_future_candles():
    dataset=candles()
    a=scan_ict_lifecycles(dataset,as_of=39)
    b=scan_ict_lifecycles(dataset[:40])
    assert a==b


def test_lifecycle_rejects_unsorted_or_incomplete():
    data=candles()
    data[9],data[10]=data[10],data[9]
    with pytest.raises(ValueError,match="UNORDERED"):
        scan_ict_lifecycles(data)
    with pytest.raises(ValueError,match="INVALID_LIFECYCLE_AS_OF"):
        scan_ict_lifecycles(candles(),as_of=81)


def test_lifecycle_export_in_replay_and_no_orders():
    result=analyze_downloaded(symbol="NIFTY",candles=candles(360))
    session=result["days"][0]
    assert "ict_lifecycles" in session
    assert all(x["order_allowed"] is False for x in session["ict_lifecycles"])
    assert result["executed_trades"]==0
